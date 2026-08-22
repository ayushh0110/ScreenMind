"""Chat routes — agent-style conversational AI with timeline access."""

import logging
import asyncio
import io
import json as _json
import re as _re
import time
from pathlib import Path

from PIL import Image as PILImage

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from screenmind.config import settings
from screenmind.api.dependencies import db, embedder

logger = logging.getLogger("screenmind.api.routes.chat")

router = APIRouter(prefix="/api", tags=["chat"])


def _build_timeline_context(primary, top, sources, send_progress):
    """
    Given a ranked list of candidate activities, build timeline_context,
    populate sources, and return (timeline_context, screenshot_path, progress_yields).
    Shared by both FTS and semantic-fallback paths to avoid drift.
    """
    progress = []
    progress.append(send_progress(f"\ud83d\udcf8 Found: {primary['app_name']} (score: {primary['_relevance']})"))

    for a in top[:5]:
        sources.append({
            "id": a["id"],
            "timestamp": a.get("timestamp", ""),
            "app_name": a.get("app_name", "Unknown"),
            "summary": (a.get("summary") or "")[:80],
            "screenshot_url": f"/api/screenshot/{a['id']}",
        })

    organized = primary.get("organized_text") or ""
    ocr_raw = primary.get("ocr_text") or ""
    screen_text = organized.strip() if organized.strip() else ocr_raw

    timeline_context = None
    screenshot_path = None

    if screen_text:
        if len(screen_text) > 3000:
            screen_text = screen_text[:3000]
        timeline_context = f"[Screen \u2014 {primary.get('app_name', 'Unknown')}]\n{screen_text}"
        screenshot_path = primary.get("screenshot_path")
    else:
        img_path = primary.get("screenshot_path")
        if img_path and Path(img_path).exists():
            progress.append(send_progress("\ud83d\udcf7 Loading screenshot..."))
            timeline_context = "vision"
            screenshot_path = img_path
        else:
            timeline_context = f"[Screen \u2014 {primary.get('app_name', 'Unknown')}]\n(no text captured)"
            screenshot_path = None

    return timeline_context, screenshot_path, progress

@router.post("/chat")
async def chat_with_memory(request: Request):
    """
    Agent-style chat: Gemma is a normal chatbot that can access
    the user's screen activity timeline when relevant.

    Flow:
    1. Extract keywords from question
    2. Quick FTS5 probe — do keywords match timeline data?
    3. YES → build timeline context → Gemma answers with context + history
    4. NO  → Gemma answers as normal chatbot with conversation history

    Follow-ups work naturally via conversation history.
    """
    from PIL import Image as _Image
    from screenmind.engine import llm_client as _llm

    t0 = time.time()
    body = await request.json()
    question = body.get("question", "").strip()
    history = body.get("history", [])
    context_range = body.get("context_range", "all")
    if not question:
        raise HTTPException(status_code=400, detail="No question provided")

    # Compute date cutoff from context_range
    from datetime import datetime as _dt_ctx, timedelta as _td_ctx
    _date_filter_sql = ""
    if context_range == "today":
        _date_cutoff = _dt_ctx.now().strftime("%Y-%m-%d")
        _date_filter_sql = f" AND DATE(timestamp) >= '{_date_cutoff}'"
    elif context_range == "7d":
        _date_cutoff = (_dt_ctx.now() - _td_ctx(days=6)).strftime("%Y-%m-%d")
        _date_filter_sql = f" AND DATE(timestamp) >= '{_date_cutoff}'"
    elif context_range == "30d":
        _date_cutoff = (_dt_ctx.now() - _td_ctx(days=29)).strftime("%Y-%m-%d")
        _date_filter_sql = f" AND DATE(timestamp) >= '{_date_cutoff}'"
    # 'all' → no filter

    conn = db._get_conn()

    async def generate():
        def send_progress(step):
            return f"data: {_json.dumps({'type': 'progress', 'step': step})}\n\n"

        def send_answer(answer, sources, mode, elapsed):
            return f"data: {_json.dumps({'type': 'answer', 'answer': answer, 'sources': sources, 'mode': mode, 'elapsed': elapsed})}\n\n"

        # ── Step 1: Extract keywords ──────────────────────────────
        STOPWORDS = {
            "what", "should", "would", "could", "will", "shall", "how", "why",
            "when", "where", "which", "who", "whom", "that", "this", "these",
            "those", "have", "has", "had", "does", "did", "doing", "done",
            "the", "and", "but", "for", "not", "you", "your", "yours",
            "they", "them", "their", "was", "were", "been", "being",
            "are", "can", "may", "might", "must", "need", "with", "from",
            "about", "into", "over", "after", "before", "between",
            "reply", "respond", "tell", "say", "said", "ask", "asked",
            "show", "see", "look", "find", "get", "got", "give", "gave",
            "last", "recent", "latest", "happening", "going", "any",
            "did", "some", "there", "also", "just", "like", "know",
            "to", "do", "me", "my", "is", "it", "in", "on", "at", "if",
            "so", "or", "no", "up", "an", "be", "am", "of",
            "i", "next", "now", "then", "than", "too",
            "message", "messages", "text", "send", "sent", "chat",
            "mail", "email", "wrote", "write", "writing",
            "hi", "hii", "hey", "hello", "please", "yeah", "yes",
            "thanks", "thank", "okay", "ok", "cool", "nice",
        }
        raw_words = [w.lower().strip("?!.,;:\'\"\"") for w in question.split()]
        q_keywords = [w for w in raw_words if len(w) > 1 and w not in STOPWORDS]

        # ── Step 2: Check timeline intent + FTS5 probe ─────────────
        timeline_context = None
        sources = []
        mode = "chat"
        primary = None
        screenshot_path = None

        # Inverted intent: default to timeline mode, skip ONLY for obvious chitchat.
        # FTS5 is the real gatekeeper — if no matches, falls to casual anyway.
        CASUAL_PATTERNS = {
            "hi", "hii", "hey", "hello", "sup", "yo",
            "thanks", "thank", "bye", "goodbye",
            "how are you", "what's up", "whats up",
            "tell me a joke", "joke", "funny",
            "who are you", "what are you", "your name",
            "good morning", "good night", "good evening",
        }
        q_lower = question.lower()
        q_words = set(q_lower.split())
        is_casual = (
            q_lower.strip("?!. ") in CASUAL_PATTERNS  # exact match: "hi", "hey"
            or (len(q_words) <= 2 and q_words & {"hi", "hii", "hey", "hello", "sup", "yo", "thanks", "bye"})
        )
        has_timeline_intent = not is_casual and bool(q_keywords)

        if q_keywords and has_timeline_intent:
            fts_ids = []
            fts_rank_map = {}  # id → FTS rank position (0 = best)
            try:
                fts_query = " OR ".join('"' + w.replace('"', '""') + '"' for w in q_keywords)
                fts_rows = conn.execute(
                    f"""SELECT a.id FROM activities_fts
                    JOIN activities a ON a.id = activities_fts.rowid
                    WHERE activities_fts MATCH ?{_date_filter_sql.replace('timestamp', 'a.timestamp')}
                    ORDER BY rank LIMIT 25""",
                    (fts_query,),
                ).fetchall()
                fts_ids = [r[0] for r in fts_rows]
                fts_rank_map = {rid: pos for pos, rid in enumerate(fts_ids)}
            except Exception as e:
                logger.error(f"FTS5 query failed: {e}")
                # Auto-repair corrupted FTS5 index
                if "malformed" in str(e).lower():
                    try:
                        db._recreate_fts(conn)
                        logger.info("FTS5 repaired, retrying query...")
                        fts_rows = conn.execute(
                            f"""SELECT a.id FROM activities_fts
                            JOIN activities a ON a.id = activities_fts.rowid
                            WHERE activities_fts MATCH ?{_date_filter_sql.replace('timestamp', 'a.timestamp')}
                            ORDER BY rank LIMIT 25""",
                            (fts_query,),
                        ).fetchall()
                        fts_ids = [r[0] for r in fts_rows]
                        fts_rank_map = {rid: pos for pos, rid in enumerate(fts_ids)}
                    except Exception as e2:
                        logger.error(f"FTS5 repair failed: {e2}")

            if fts_ids:
                yield send_progress(f"🔍 Searching timeline for: {', '.join(q_keywords)}")

                # ── Load FTS candidates with embeddings ──
                placeholders = ",".join("?" * len(fts_ids))
                candidate_rows = conn.execute(
                    f"""SELECT id, timestamp, app_name, category, summary, details,
                           ocr_text, organized_text, screenshot_path, window_title,
                           scene_description, embedding
                    FROM activities
                    WHERE id IN ({placeholders}) AND status = 'ok'{_date_filter_sql}
                    ORDER BY timestamp DESC""",
                    fts_ids,
                ).fetchall()
                candidates = [dict(r) for r in candidate_rows]

                # ── Expand: if FTS returned few, supplement with recent activities ──
                if len(candidates) < 3:
                    existing_ids = {a["id"] for a in candidates}
                    fill_rows = conn.execute(
                        f"""SELECT id, timestamp, app_name, category, summary, details,
                               ocr_text, organized_text, screenshot_path, window_title,
                               scene_description, embedding
                        FROM activities
                        WHERE status = 'ok' AND embedding IS NOT NULL{_date_filter_sql}
                        ORDER BY timestamp DESC LIMIT 10""",
                    ).fetchall()
                    for r in fill_rows:
                        d = dict(r)
                        if d["id"] not in existing_ids:
                            candidates.append(d)
                            existing_ids.add(d["id"])
                        if len(candidates) >= 10:
                            break

                # ── Semantic re-ranking ──
                top = []
                if embedder and candidates:
                    emb_data = []  # (candidate_index, embedding_vector)
                    for i, a in enumerate(candidates):
                        emb = db._decode_embedding(a.pop("embedding", None))
                        if emb:
                            emb_data.append((i, emb))

                    if emb_data:
                        indices, vectors = zip(*emb_data)
                        ranked = embedder.search(question, list(vectors), top_k=min(5, len(vectors)))

                        from datetime import datetime as _dt
                        now = _dt.now()
                        scored = []
                        for local_idx, sem_score in ranked:
                            orig_idx = indices[local_idx]
                            a = candidates[orig_idx]
                            # Recency boost: gentle decay over hours
                            try:
                                ts = _dt.fromisoformat(a.get("timestamp", ""))
                                age_hours = max((now - ts).total_seconds() / 3600, 0)
                            except Exception:
                                age_hours = 24
                            recency_boost = 1.0 / (1.0 + age_hours * 0.05)
                            # FTS rank boost: top FTS result gets +0.1
                            fts_pos = fts_rank_map.get(a["id"], len(fts_ids))
                            fts_boost = 0.1 * (1.0 - fts_pos / max(len(fts_ids), 1))
                            # Final hybrid score
                            final = (sem_score * 0.7) + (recency_boost * 0.2) + (fts_boost * 0.1)
                            a["_relevance"] = round(final, 3)
                            scored.append(a)

                        # Add unscored candidates (no embeddings) at end
                        scored_ids = {a["id"] for a in scored}
                        for a in candidates:
                            if a["id"] not in scored_ids:
                                a["_relevance"] = 0.05
                                scored.append(a)

                        scored.sort(key=lambda x: x["_relevance"], reverse=True)
                        top = scored[:5]
                    else:
                        # No embeddings — fall back to FTS rank order
                        for a in candidates:
                            a["_relevance"] = 0.5
                        top = candidates[:5]
                else:
                    # No embedder — fall back to FTS rank order
                    for a in candidates:
                        a["_relevance"] = 0.5
                    top = candidates[:5]

                # ── Guard: if candidates were deleted between probe and SELECT ──
                if top:
                    primary = top[0]
                    ctx, ss_path, prog = _build_timeline_context(primary, top, sources, send_progress)
                    for p in prog:
                        yield p
                    if ctx is not None:
                        timeline_context = ctx
                        screenshot_path = ss_path
                        mode = "memory"

            # ── Semantic fallback ─────────────────────────────────
            # If FTS5 returned nothing (or was broken), try pure embedding search
            if timeline_context is None and embedder:
                yield send_progress(f"🔍 Searching timeline for: {', '.join(q_keywords)}")

                fallback_rows = conn.execute(
                    f"""SELECT id, timestamp, app_name, category, summary, details,
                           ocr_text, organized_text, screenshot_path, window_title,
                           scene_description, embedding
                    FROM activities
                    WHERE status = 'ok' AND embedding IS NOT NULL{_date_filter_sql}
                    ORDER BY timestamp DESC LIMIT 500""",
                ).fetchall()
                fb_candidates = [dict(r) for r in fallback_rows]

                if fb_candidates:
                    emb_data = []
                    for i, a in enumerate(fb_candidates):
                        emb = db._decode_embedding(a.pop("embedding", None))
                        if emb:
                            emb_data.append((i, emb))

                    if emb_data:
                        indices, vectors = zip(*emb_data)
                        ranked = embedder.search(question, list(vectors), top_k=min(5, len(vectors)))

                        top = []
                        for local_idx, sem_score in ranked:
                            orig_idx = indices[local_idx]
                            a = fb_candidates[orig_idx]
                            a["_relevance"] = round(sem_score, 3)
                            top.append(a)

                        # Relevance gate: only enter memory mode if top result is meaningful
                        if top and top[0]["_relevance"] >= 0.35:
                            primary = top[0]
                            ctx, ss_path, prog = _build_timeline_context(primary, top, sources, send_progress)
                            for p in prog:
                                yield p
                            if ctx is not None:
                                timeline_context = ctx
                                screenshot_path = ss_path
                                mode = "memory"

        # ── Step 3: Build messages ────────────────────────────────

        if timeline_context == "vision":
            app = primary.get("app_name", "").lower() if primary else ""
            if "discord" in app:
                sys_msg = (
                    "This is a Discord screenshot. "
                    "Focus ONLY on the CHAT AREA (center) — the actual conversation messages. "
                    "IGNORE: sidebar, Nitro ads, profile panels, UI buttons. "
                    "Answer the user's question directly and concisely. "
                    "Quote only the relevant messages — do NOT list everything."
                )
            elif "gmail" in app or "mail" in app or "outlook" in app:
                sys_msg = (
                    "This is an email inbox screenshot. "
                    "Answer the user's question by scanning the visible email list. "
                    "Only mention emails that are RELEVANT to the question. "
                    "Do NOT list every email — only quote matching ones. "
                    "If none match, say so clearly."
                )
            else:
                sys_msg = (
                    "This is a screenshot from the user's screen. "
                    "Answer the question directly based on what you see. "
                    "Focus on the MAIN CONTENT area — ignore taskbar and system UI. "
                    "Be specific and concise — quote only relevant text."
                )
        elif timeline_context:
            sections_found = _re.findall(r'\[([^\]]+)\]', timeline_context)
            scene = primary.get("scene_description", "") if primary else ""
            app_name = primary.get("app_name", "Unknown") if primary else "Unknown"

            hints = []
            for s in sections_found:
                sl = s.lower()
                if 'chat' in sl or 'message' in sl:
                    hints.append("Chat messages are formatted as 'sender: message1 | message2'.")
                elif 'email' in sl or 'inbox' in sl:
                    hints.append("Email rows show: sender, subject, and preview text.")
                elif 'sidebar' in sl or 'nav' in sl:
                    hints.append(f"[{s}] contains navigation/menu items.")
                elif 'profile' in sl:
                    hints.append(f"[{s}] contains user profile info.")

            section_hint = " ".join(hints) if hints else ""

            sys_msg = (
                f"You are the user's AI memory assistant. "
                f"Below is text extracted from a {app_name} screenshot, organized by visual sections. "
                f"{section_hint} "
                f"{('Scene: ' + scene + '. ') if scene else ''}"
                f"Answer the user's question based on the text. "
                f"Be specific — quote actual text from the screen when relevant."
            )
        else:
            sys_msg = ("You are ScreenMind, a warm and witty AI assistant that lives on the user's computer. "
                       "You can see their screen activity when they ask about it. "
                       "Chat casually — tell jokes, brainstorm ideas, have fun conversations. "
                       "Keep responses concise (2-3 sentences for casual chat, longer for complex topics). "
                       "Be friendly and natural, like a smart friend.")

        messages = [{"role": "system", "content": sys_msg}]

        if not timeline_context:
            # Casual mode: full conversation history for continuity
            for h in history[-6:]:
                messages.append({
                    "role": h.get("role", "user"),
                    "content": h.get("content", ""),
                })
        elif history:
            # Timeline mode: include last 2 exchanges (truncated) for follow-up context
            # e.g. "what was her last message" needs to know Q1 was about Ishaa on Discord
            for h in history[-2:]:
                messages.append({
                    "role": h.get("role", "user"),
                    "content": h.get("content", "")[:200],
                })

        if timeline_context == "vision":
            from screenmind.privacy.encryption import open_image as _enc_open
            img = _enc_open(screenshot_path)
            if max(img.size) > 1280:
                ratio = 1280 / max(img.size)
                img = img.resize(
                    (int(img.size[0]*ratio), int(img.size[1]*ratio)),
                    PILImage.Resampling.LANCZOS,
                )
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)

            ocr = (primary.get("organized_text") or primary.get("ocr_text") or "").strip()
            user_content = question
            if ocr and q_keywords:
                ocr_lines = [l.strip() for l in ocr.split('\n') if len(l.strip()) > 2]
                relevant = [l for l in ocr_lines
                            if any(k.lower() in l.lower() for k in q_keywords)]
                if relevant:
                    snippet = '\n'.join(relevant[:10])
                    user_content = f"Relevant text from screen:\n{snippet}\n\nQuestion: {question}"

            import base64 as _b64
            img_b64 = _b64.b64encode(buf.getvalue()).decode()
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_content},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                ],
            })
        elif timeline_context:
            messages.append({"role": "user", "content": f"Here is text from my screen:\n\n{timeline_context}\n\nQuestion: {question}"})
        else:
            messages.append({"role": "user", "content": question})

        # ── Step 4: Gemma call ────────────────────────────────────

        # Pre-empt: cancel any in-flight analysis so chat gets GPU immediately
        if _llm.is_inference_active():
            _llm.cancel_current_inference()
            yield send_progress("⏳ Waiting for GPU...")
            # Poll llama-server /slots until the slot is free (or timeout)
            import httpx as _httpx
            _slot_free = False
            for _wait_i in range(20):  # 20 × 0.5s = 10s max
                await asyncio.sleep(0.5)
                try:
                    _sr = _httpx.get(f"{_llm._base_url()}/slots", timeout=2)
                    if _sr.status_code == 200:
                        _slots = _sr.json()
                        if isinstance(_slots, list) and all(not s.get("is_processing") for s in _slots):
                            _slot_free = True
                            break
                except Exception:
                    pass
            if not _slot_free:
                logger.info("GPU slot still busy after 10s — proceeding anyway")

        logger.debug(f"Mode: {'vision' if timeline_context == 'vision' else 'text' if timeline_context else 'chat'} | Messages: {len(messages)}")

        yield send_progress(f"🤖 {'Analyzing screenshot...' if timeline_context == 'vision' else 'Analyzing...' if timeline_context else 'Thinking...'}")

        answer = ""
        try:
            response_text = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _llm.chat(
                    messages=messages,
                    temperature=0.1 if timeline_context else 0.7,
                    max_tokens=2048 if timeline_context == "vision" else 1024 if timeline_context else 768,
                ),
            )
            answer = response_text

            # Empty response detection
            if not answer.strip() and timeline_context:
                logger.info("Empty response — retrying...")
                yield send_progress("⚠️ Empty response, retrying...")
                await asyncio.sleep(2)

                try:
                    answer = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: _llm.chat(
                            messages=messages,
                            temperature=0.1,
                            max_tokens=1024,
                        ),
                    )
                except Exception:
                    pass

                if not answer.strip() and screenshot_path and Path(screenshot_path).exists():
                    logger.info("Still empty after retry — falling back to vision...")
                    yield send_progress("📷 Trying screenshot fallback...")
                    mode = "vision"
                    try:
                        from screenmind.privacy.encryption import open_image as _enc_open
                        img = _enc_open(screenshot_path)
                        if max(img.size) > 1280:
                            ratio = 1280 / max(img.size)
                            img = img.resize(
                                (int(img.size[0]*ratio), int(img.size[1]*ratio)),
                                _Image.Resampling.LANCZOS,
                            )
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=85)
                        answer = await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: _llm.chat_with_images(
                                prompt=f"Look at this screenshot. {question}",
                                images=[buf.getvalue()],
                                temperature=0.3,
                                max_tokens=1024,
                            ),
                        )
                    except Exception:
                        pass

        except Exception as e:
            if timeline_context and screenshot_path and Path(screenshot_path).exists():
                yield send_progress("📷 Trying screenshot fallback...")
                mode = "vision"
                try:
                    from screenmind.privacy.encryption import open_image as _enc_open
                    img = _enc_open(screenshot_path)
                    if max(img.size) > 1536:
                        ratio = 1536 / max(img.size)
                        img = img.resize(
                            (int(img.size[0]*ratio), int(img.size[1]*ratio)),
                            PILImage.Resampling.LANCZOS,
                        )
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=90)
                    answer = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: _llm.chat_with_images(
                            prompt=f"Look at this screenshot. {question}",
                            images=[buf.getvalue()],
                            temperature=0.3,
                            max_tokens=1024,
                        ),
                    )
                except Exception as e2:
                    answer = f"Sorry, error: {str(e2)[:100]}"
            else:
                answer = f"Sorry, I'm having trouble connecting: {str(e)[:100]}"

        elapsed = round(time.time() - t0, 1)
        yield send_progress(f"✅ {elapsed}s")
        yield send_answer(answer, sources, mode, elapsed)

    return StreamingResponse(generate(), media_type="text/event-stream")
