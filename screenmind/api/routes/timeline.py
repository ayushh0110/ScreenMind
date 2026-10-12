"""Timeline routes — list activities, activity detail, delete, reanalyze."""

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from screenmind.config import settings
from screenmind.api.dependencies import db

router = APIRouter(prefix="/api", tags=["timeline"])


@router.get("/timeline")
async def get_timeline(
    date: str = Query(default=None),
    since: str = Query(default=None, description="ISO timestamp cutoff — only return activities after this time"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Get activities for a specific date, optionally filtered by since timestamp."""
    target_date = date or str(__import__("datetime").date.today())
    activities = db.get_activities_by_date(target_date, limit=limit, offset=offset)
    if since:
        activities = [a for a in activities if a.get("timestamp", "") >= since]
    for a in activities:
        if a.get("screenshot_path"):
            a["screenshot_url"] = f"/api/screenshot/{a['id']}"
    return {"date": target_date, "activities": activities}


@router.get("/activity/{activity_id}")
async def get_activity(activity_id: int):
    """Get a single activity with full details."""
    activity = db.get_activity_by_id(activity_id)
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    if activity.get("screenshot_path"):
        activity["screenshot_url"] = f"/api/screenshot/{activity['id']}"
    return activity


@router.delete("/activities/{activity_id}")
async def delete_activity(activity_id: int):
    """Delete a single activity and its screenshot."""
    conn = db._get_conn()
    row = conn.execute(
        "SELECT screenshot_path FROM activities WHERE id = ?", (activity_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Activity not found")

    # Delete screenshot file
    ss_path = row[0] if row else None
    if ss_path and Path(ss_path).exists():
        try:
            Path(ss_path).unlink()
        except OSError:
            pass

    # Delete from DB
    conn.execute("DELETE FROM activities WHERE id = ?", (activity_id,))
    conn.commit()
    return {"deleted": True, "activity_id": activity_id}


async def _retranscribe_voice_memo(activity_id: int, wav_path: Path) -> dict:
    """Re-run audio transcription for a voice memo."""
    from screenmind.engine import model_manager
    from screenmind.engine.voice_memo import retranscribe_memo

    if not wav_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    if not model_manager.is_audio_capable():
        active = model_manager.get_active_model() or "unknown"
        raise HTTPException(
            status_code=409,
            detail=f"Model '{active}' does not support audio. Switch to Gemma 4 E2B or E4B to re-transcribe.",
        )

    try:
        result = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None, lambda: retranscribe_memo(db, activity_id, wav_path)
            ),
            timeout=300,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Re-transcription timed out (server unresponsive)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Re-transcription failed: {str(e)[:200]}")

    if result["status"] != "ok":
        raise HTTPException(status_code=422, detail="No speech recognized in the recording")

    return {
        "reanalyzed": True,
        "activity_id": activity_id,
        "type": "voice_memo",
        "summary": result["transcript"][:200],
    }


@router.post("/activities/{activity_id}/reanalyze")
async def reanalyze_activity(activity_id: int):
    """Re-run analysis on a single activity.

    Voice memos (details holds a WAV path under the memos directory) are
    re-transcribed; everything else gets Gemma analysis + layout detection.
    """
    conn = db._get_conn()
    row = conn.execute(
        """SELECT screenshot_path, ocr_text, ocr_boxes, detected_app, window_title,
                  details, active_url
           FROM activities WHERE id = ?""",
        (activity_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Activity not found")

    from screenmind.engine.voice_memo import memo_wav_path
    wav_path = memo_wav_path(row["details"])
    if wav_path is not None:
        return await _retranscribe_voice_memo(activity_id, wav_path)

    ss_path = row["screenshot_path"]
    if not ss_path or not Path(ss_path).exists():
        raise HTTPException(status_code=400, detail="Screenshot not found")

    from PIL import Image as _Image
    from screenmind.engine.analyzer import GemmaAnalyzer
    from screenmind.engine.layout_analyzer import organize_ocr_text, cluster_ocr_layout
    from screenmind.config import settings as app_settings

    try:
        from screenmind.privacy.encryption import open_image as _enc_open
        img = _enc_open(ss_path)

        # Re-run Gemma analysis (respects analysis_mode setting)
        ocr_text = row["ocr_text"] or ""
        app_name = row["detected_app"] or None
        window_title = row["window_title"] or None

        # Extract URLs from OCR text (same as analysis_worker)
        from screenmind.workers.analysis_worker import _extract_all_urls
        active_urls = _extract_all_urls(ocr_text) if ocr_text else []

        analyzer = GemmaAnalyzer()
        try:
            _MODE_MAP = {
                "fast": analyzer.analyze_screenshot_fast,
                "balanced": analyzer.analyze_screenshot_balanced,
                "merged": analyzer.analyze_screenshot,
            }
            analyze_fn = _MODE_MAP.get(app_settings.analysis_mode, analyzer.analyze_screenshot_fast)
            record, layout_regions = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: analyze_fn(
                        image=img,
                        window_title=window_title,
                        app_name_hint=app_name,
                        ocr_text=ocr_text,
                        active_urls=active_urls,
                    ),
                ),
                timeout=300,
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Re-analysis timed out (server unresponsive)")


        # Organize text using layout regions (Gemma regions or OCR clustering)
        organized_text = ""
        ocr_boxes_raw = row["ocr_boxes"]
        if ocr_boxes_raw:
            ocr_boxes = json.loads(ocr_boxes_raw)
            try:
                screen_w, screen_h = img.size
                regions = layout_regions if layout_regions else cluster_ocr_layout(ocr_boxes, screen_w, screen_h)
                organized_text = organize_ocr_text(
                    ocr_boxes, regions, screen_w, screen_h
                )
            except Exception as e:
                organized_text = ""  # Non-fatal — skip layout on error

        # Generate embedding for semantic search
        embedding = None
        try:
            from screenmind.api.dependencies import embedder as _emb
            if _emb:
                embedding = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: _emb.embed_activity(
                        summary=record.activity_summary,
                        details=record.detailed_context,
                        visible_text=record.visible_text_snippets,
                        app_name=record.app_name,
                        category=record.activity_category,
                        scene_description=record.scene_description,
                    ),
                )
        except Exception:
            pass  # Non-fatal — search still works via FTS

        # Update DB (handles FTS5 sync automatically). OCR boxes and the URL
        # are passed through so re-analysis doesn't wipe search highlighting.
        db.update_activity_analysis(
            activity_id=activity_id,
            analysis=record,
            embedding=embedding,
            ocr_text=ocr_text,
            ocr_boxes=ocr_boxes_raw,
            organized_text=organized_text,
            analysis_method="reanalyze",
            active_url=active_urls[0] if active_urls else row["active_url"],
        )

        return {
            "reanalyzed": True,
            "activity_id": activity_id,
            "summary": record.activity_summary,
            "category": record.activity_category,
        }
    except HTTPException:
        raise  # Re-raise timeout 504
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Re-analysis failed: {str(e)[:200]}")
