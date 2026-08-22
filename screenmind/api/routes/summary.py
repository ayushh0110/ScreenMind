"""Summary & Standup routes — AI-generated daily summaries."""

import logging
import asyncio
from collections import Counter
from datetime import datetime as dt

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from screenmind.config import settings
from screenmind.api.dependencies import db

logger = logging.getLogger("screenmind.api.routes.summary")

router = APIRouter(prefix="/api", tags=["summary"])


# Categories that count as focused/productive work time.
# Browsing and communication are excluded — they can be doomscrolling/chat.
_PRODUCTIVE_CATEGORIES = {"coding", "writing", "terminal", "design", "meeting"}


def _compute_day_metrics(activities: list) -> dict:
    """Compute productive_hours, category_breakdown, and top_repos from activities.

    Uses actual timestamps with per-gap capping for accuracy instead of
    count × capture_interval which overcounts rapid-fire frames and
    undercounts long static work sessions.
    """
    analyzed = [a for a in activities if a.get("status") == "ok"]
    if not analyzed:
        return {"productive_hours": 0.0, "category_breakdown": {}, "top_repos": []}

    # Category breakdown
    category_counts = Counter(
        (a.get("category") or "other") for a in analyzed
    )

    # Productive hours from timestamps — sort chronologically, sum capped deltas
    max_gap = 2 * settings.capture_interval  # Cap per gap (e.g. 80s at default 40s)
    productive_seconds = 0.0
    productive_entries = sorted(
        [a for a in analyzed if (a.get("category") or "other").lower() in _PRODUCTIVE_CATEGORIES],
        key=lambda a: a.get("timestamp", ""),
    )
    for i, a in enumerate(productive_entries):
        if i == 0:
            # First entry: count one interval
            productive_seconds += settings.capture_interval
            continue
        try:
            prev_ts = dt.fromisoformat(productive_entries[i - 1]["timestamp"])
            curr_ts = dt.fromisoformat(a["timestamp"])
            delta = (curr_ts - prev_ts).total_seconds()
            productive_seconds += min(delta, max_gap)
        except (ValueError, KeyError, TypeError):
            productive_seconds += settings.capture_interval

    productive_hours = round(productive_seconds / 3600, 2)

    # Top repos from dev_context JOIN
    repo_counts = Counter(
        a["repo_name"] for a in analyzed
        if a.get("repo_name")
    )
    top_repos = [repo for repo, _ in repo_counts.most_common(5)]

    return {
        "productive_hours": productive_hours,
        "category_breakdown": dict(category_counts),
        "top_repos": top_repos,
    }


@router.get("/summary")
async def get_summary(
    date: str = Query(default=None),
):
    target = date or str(__import__("datetime").date.today())
    summary = db.get_daily_summary(target)
    return {"date": target, "generated": summary is not None, "summary": summary, "standup": (summary or {}).get("standup", "")}


@router.post("/summary/generate")
async def generate_summary(
    date: str = Query(default=None),
):
    """Generate a daily summary using Gemma 4."""
    from screenmind.engine import llm_client
    from screenmind.storage.models import DailySummary

    target = date or str(__import__("datetime").date.today())
    activities = db.get_activities_by_date(target, limit=200)

    if not activities:
        return {"date": target, "summary": {"summary": "No activities recorded on this date."}}

    # Snapshot real count before any filtering/trimming — this is "how much
    # happened today", not "how much fit in the prompt".
    real_count = sum(1 for a in activities if a.get("status") == "ok")

    if real_count == 0:
        return {"date": target, "summary": {"summary": "No analyzed activities on this date."}}

    # Adapt output size to context window — don't request 2048 on a 4096 window
    max_output = min(2048, settings.context_window // 3)

    # Budget: (context_window - output - safety margin) * ~3.0 chars/token
    # Using 3.0 (conservative) rather than 3.5 to account for CJK/code/OCR text.
    # The 150-entry cap is the real safety net for pathological inputs.
    prompt_template_chars = 350  # The rules/wrapper text around {acts_text}
    available_tokens = settings.context_window - max_output - 300
    char_budget = int(available_tokens * 3.0) - prompt_template_chars

    # Build rich context — only include real analyses (status='ok')
    MAX_RICH = 20
    MAX_ENTRIES = 150  # Secondary guard for pathological inputs
    act_entries = []
    rich_count = 0
    for a in activities:
        if a.get("status") != "ok":
            continue
        if len(act_entries) >= MAX_ENTRIES:
            break
        time_str = a.get("timestamp", "")
        app = a.get("app_name", "?")
        cat = a.get("category", "?")
        summary = a.get("summary", "")
        entry = f"[{time_str}] {app} ({cat}): {summary}"
        if rich_count < MAX_RICH:
            org_text = (a.get("organized_text") or "").strip()
            if org_text:
                if len(org_text) > 300:
                    org_text = org_text[:300] + "..."
                entry += f"\n  Screen content: {org_text}"
                rich_count += 1
        act_entries.append(entry)

    # Trim oldest entries (end of list, since ordered DESC) until prompt fits budget
    total_chars = sum(len(e) for e in act_entries) + len(act_entries)  # +newlines
    while total_chars > char_budget and act_entries:
        total_chars -= len(act_entries.pop()) + 1

    acts_text = "\n".join(act_entries)
    act_count = len(act_entries)

    prompt = f"""Summarize this user's day based on their screen activities.

Rules:
- Be SPECIFIC: mention actual names, email subjects, chat contacts, repo names — not vague descriptions
- Scale your response to the data: {act_count} activities = {1 if act_count <= 5 else 2 if act_count <= 15 else 3}-{2 if act_count <= 5 else 3 if act_count <= 15 else 5} short paragraphs
- Don't pad with filler. If there's little data, write a short summary
- Use the "Screen content" fields for specific details (who messaged, what emails, etc.)

Activities:
{acts_text}

Write the summary:"""

    try:
        summary_text = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: llm_client.generate(
                prompt=prompt,
                temperature=0.3,
                max_tokens=max_output,
            ),
        )
        if not summary_text or not summary_text.strip():
            raise ValueError("Empty response from LLM")
    except Exception as e:
        logger.error(f"Summary generation failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

    # Only on success — persist + fire integrations
    metrics = _compute_day_metrics(activities)

    summary_obj = DailySummary(
        date=target,
        summary=summary_text,
        total_activities=real_count,
        category_breakdown=metrics["category_breakdown"],
        productive_hours=metrics["productive_hours"],
        top_repos=metrics["top_repos"],
    )
    db.upsert_daily_summary(summary_obj)

    # Fire integrations
    _fire_summary_integrations(target, summary_text, "", real_count)

    return {"date": target, "summary": {"summary": summary_text}}


@router.post("/standup/generate")
async def generate_standup(
    date: str = Query(default=None),
):
    """Generate standup notes."""
    from screenmind.engine import llm_client

    target = date or str(__import__("datetime").date.today())
    activities = db.get_activities_by_date(target, limit=200)

    if not activities:
        return {"date": target, "standup": "No activities to summarize."}

    # Snapshot real count before any filtering/trimming
    real_count = sum(1 for a in activities if a.get("status") == "ok")

    if real_count == 0:
        return {"date": target, "standup": "No analyzed activities to summarize."}

    # Adapt output size to context window
    max_output = min(1024, settings.context_window // 4)

    # Budget for standup prompt
    prompt_template_chars = 450  # The rules/format text around {acts_text}
    available_tokens = settings.context_window - max_output - 300
    char_budget = int(available_tokens * 3.0) - prompt_template_chars

    MAX_RICH = 15
    MAX_ENTRIES = 150
    act_entries = []
    rich_count = 0
    for a in activities:
        if a.get("status") != "ok":
            continue
        if len(act_entries) >= MAX_ENTRIES:
            break
        app = a.get("app_name", "?")
        summary = a.get("summary", "")
        entry = f"- {app}: {summary}"
        if rich_count < MAX_RICH:
            org_text = (a.get("organized_text") or "").strip()
            if org_text:
                if len(org_text) > 200:
                    org_text = org_text[:200] + "..."
                entry += f"\n  Content: {org_text}"
                rich_count += 1
        act_entries.append(entry)

    # Trim oldest entries until prompt fits budget
    total_chars = sum(len(e) for e in act_entries) + len(act_entries)
    while total_chars > char_budget and act_entries:
        total_chars -= len(act_entries.pop()) + 1

    acts_text = "\n".join(act_entries)

    prompt = f"""Generate standup notes from these screen activities.

Rules:
- Be SPECIFIC: use actual names, subjects, contacts from the "Content" fields
- Keep each bullet point to 1 line — no vague descriptions
- If few activities, keep it short (2-3 bullets per section max)
- "Blockers" should be real issues visible in the data, or say "None identified"

Format:
## Yesterday / Today
- Specific things done (e.g. "Replied to aachii on Discord", "Checked Gmail inbox — portfolio/main")
## Blockers
- Real issues or "None identified"
## Plan
- Concrete next steps based on what was seen

Activities:
{acts_text}"""

    try:
        standup = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: llm_client.generate(
                prompt=prompt,
                temperature=0.3,
                max_tokens=max_output,
            ),
        )
        if not standup or not standup.strip():
            raise ValueError("Empty response from LLM")
    except Exception as e:
        logger.error(f"Standup generation failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

    # Only on success — persist + fire integrations
    from screenmind.storage.models import DailySummary
    metrics = _compute_day_metrics(activities)
    standup_summary = DailySummary(
        date=target,
        summary="",  # Don't overwrite existing summary
        total_activities=real_count,
        category_breakdown=metrics["category_breakdown"],
        productive_hours=metrics["productive_hours"],
        top_repos=metrics["top_repos"],
    )
    db.upsert_daily_summary(standup_summary, standup=standup)

    # Fire integrations
    _fire_summary_integrations(target, "", standup, real_count)

    return {"date": target, "standup": standup}


def _fire_summary_integrations(date_str: str, summary: str, standup: str, activity_count: int):
    """Fire all enabled integrations after summary/standup generation."""
    try:
        if settings.obsidian_enabled and settings.obsidian_vault_path:
            from screenmind.integrations.obsidian import export_summary
            export_summary(settings.obsidian_vault_path, date_str, summary, standup, activity_count)
    except Exception as e:
        logger.error(f"Obsidian error: {e}")

    try:
        if settings.notion_enabled and settings.notion_token:
            from screenmind.integrations.notion import export_summary
            export_summary(settings.notion_token, settings.notion_database_id, date_str, summary, standup, activity_count)
    except Exception as e:
        logger.error(f"Notion error: {e}")

    try:
        if settings.webhook_enabled and settings.webhook_url:
            from screenmind.integrations.webhooks import fire
            fire("daily_summary", {
                "date": date_str,
                "summary": summary,
                "standup": standup,
                "activity_count": activity_count,
            }, settings.webhook_url, settings.webhook_secret, settings.webhook_events, settings.webhook_headers)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
