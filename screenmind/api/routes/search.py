"""Search routes — semantic + FTS5 hybrid search."""

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from screenmind.api.dependencies import db, embedder

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search")
async def search_activities(
    q: str = Query(..., description="Search query"),
    limit: int = Query(default=20, ge=1, le=50),
    category: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
):
    """Semantic search across all activities."""
    if not embedder:
        raise HTTPException(status_code=503, detail="Embedder not available")

    conn = db._get_conn()

    where_clauses = ["status = 'ok'", "embedding IS NOT NULL"]
    params = []

    if category:
        where_clauses.append("category = ?")
        params.append(category)
    if date_from:
        where_clauses.append("DATE(timestamp) >= ?")
        params.append(date_from)
    if date_to:
        where_clauses.append("DATE(timestamp) <= ?")
        params.append(date_to)

    where = " AND ".join(where_clauses)
    rows = conn.execute(
        f"""
        SELECT id, timestamp, app_name, category, summary, details,
               visible_text, bookmarked, embedding, ocr_text
        FROM activities
        WHERE {where}
        ORDER BY timestamp DESC
        LIMIT 500
        """,
        params,
    ).fetchall()

    activities_data = []
    embeddings_list = []

    for row in rows:
        row_dict = dict(row)
        emb = db._decode_embedding(row_dict.get("embedding"))
        if emb:
            row_dict.pop("embedding", None)
            ocr_full = row_dict.pop("ocr_text", None) or ""
            row_dict["ocr_snippet"] = ocr_full[:200] if ocr_full else ""
            row_dict["screenshot_url"] = f"/api/screenshot/{row_dict['id']}"
            activities_data.append(row_dict)
            embeddings_list.append(emb)

    search_results = []
    seen_ids = set()

    # 1. Semantic search
    if embeddings_list:
        results = await asyncio.get_event_loop().run_in_executor(
            None, lambda: embedder.search(q, embeddings_list, top_k=limit)
        )
        for idx, score in results:
            item = activities_data[idx].copy()
            item["relevance_score"] = round(score, 3)
            item["match_type"] = "semantic"
            search_results.append(item)
            seen_ids.add(item["id"])

    # 2. FTS5 keyword fallback
    try:
        # Escape FTS5 special characters by wrapping in double quotes
        fts_query = '"' + q.replace('"', '""') + '"'

        fts_date_clauses = []
        fts_date_params = []
        if date_from:
            fts_date_clauses.append("DATE(a.timestamp) >= ?")
            fts_date_params.append(date_from)
        if date_to:
            fts_date_clauses.append("DATE(a.timestamp) <= ?")
            fts_date_params.append(date_to)
        fts_date_where = (" AND " + " AND ".join(fts_date_clauses)) if fts_date_clauses else ""

        fts_rows = conn.execute(
            f"""
            SELECT a.id, a.timestamp, a.app_name, a.category, a.summary,
                   a.details, a.screenshot_path, a.bookmarked, a.mood, fts.rank
            FROM activities_fts fts
            JOIN activities a ON a.id = fts.rowid
            WHERE activities_fts MATCH ? AND a.status = 'ok'{fts_date_where}
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, *fts_date_params, limit),
        ).fetchall()

        for i, row in enumerate(fts_rows):
            row_dict = dict(row)
            # FTS5 rank is negative (closer to 0 = better match)
            # Convert to 0.3-0.7 range based on position in results
            fts_score = round(0.7 - (i * 0.4 / max(len(fts_rows) - 1, 1)), 3)
            row_dict.pop("rank", None)
            if row_dict["id"] not in seen_ids:
                row_dict["screenshot_url"] = f"/api/screenshot/{row_dict['id']}"
                row_dict["relevance_score"] = fts_score
                row_dict["match_type"] = "keyword"
                search_results.append(row_dict)
                seen_ids.add(row_dict["id"])
            else:
                # Boost semantic result if also matched by FTS
                for r in search_results:
                    if r["id"] == row_dict["id"]:
                        r["relevance_score"] = min(r["relevance_score"] + 0.1, 1.0)
                        r["match_type"] = "hybrid"
                        break
    except Exception:
        pass

    # 3. Meeting transcript search
    try:
        mtg_date_clauses = []
        mtg_date_params = []
        if date_from:
            mtg_date_clauses.append("DATE(start_time) >= ?")
            mtg_date_params.append(date_from)
        if date_to:
            mtg_date_clauses.append("DATE(start_time) <= ?")
            mtg_date_params.append(date_to)
        mtg_date_where = (" AND " + " AND ".join(mtg_date_clauses)) if mtg_date_clauses else ""

        mtg_rows = conn.execute(
            f"""
            SELECT id, start_time, end_time, app_name, duration_minutes,
                   transcript, summary
            FROM meetings
            WHERE (transcript LIKE ? OR summary LIKE ?){mtg_date_where}
            ORDER BY start_time DESC
            LIMIT ?
            """,
            (f"%{q}%", f"%{q}%", *mtg_date_params, limit),
        ).fetchall()

        for row in mtg_rows:
            d = dict(row)
            transcript = d.get("transcript") or ""
            snippet = ""
            q_lower = q.lower()
            idx = transcript.lower().find(q_lower)
            if idx >= 0:
                start = max(0, idx - 80)
                end = min(len(transcript), idx + len(q) + 80)
                snippet = ("..." if start > 0 else "") + transcript[start:end] + ("..." if end < len(transcript) else "")
            else:
                snippet = transcript[:200]

            search_results.append({
                "id": f"meeting-{d['id']}",
                "timestamp": d["start_time"],
                "app_name": d.get("app_name") or "Meeting",
                "category": "meeting",
                "summary": d.get("summary") or "Meeting transcript",
                "details": snippet,
                "relevance_score": 0.6,
                "match_type": "meeting",
                "duration_minutes": d.get("duration_minutes"),
            })
    except Exception:
        pass

    search_results.sort(key=lambda x: x["relevance_score"], reverse=True)
    search_results = search_results[:limit]

    return {"query": q, "count": len(search_results), "results": search_results}
