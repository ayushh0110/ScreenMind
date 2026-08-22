"""
ScreenMind MCP Server
Exposes screen history, search, and capture tools via the Model Context Protocol.
Compatible with Claude Desktop, Cursor, VS Code (Cline/Continue), and any MCP client.

Usage:
  python -m screenmind.mcp_server   # stdio transport (for Claude Desktop / Cursor)

Claude Desktop config (~/.claude/claude_desktop_config.json):
  {
    "mcpServers": {
      "screenmind": {
        "command": "python",
        "args": ["-m", "screenmind.mcp_server"]
      }
    }
  }
"""

import json
import logging
import sys

# ── CRITICAL: Redirect stdout prints to stderr ──────────────────────────
# MCP stdio transport uses stdout for protocol messages.
# Any print() from libraries (Embedder, Database, Config) would corrupt the protocol.
# We redirect ALL print output to stderr, then restore stdout for MCP.
# Only when running as main script — not when imported as a module.
_real_stdout = sys.stdout
if __name__ == "__main__":
    sys.stdout = sys.stderr

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: MCP server requires the 'mcp' package.", file=sys.stderr)  # noqa: T201
    print("Install with:  pip install screenmind[mcp]", file=sys.stderr)  # noqa: T201
    sys.exit(1)

from datetime import date, datetime, timedelta
from typing import Optional

from screenmind.config import settings
from screenmind.engine.embedder import Embedder
from screenmind.storage.database import Database

logger = logging.getLogger("screenmind.mcp_server")

# ── Initialize ──────────────────────────────────────────────────────────
db = Database()
embedder = Embedder()
try:
    embedder._ensure_model()
except Exception:
    logger.warning("Embedder unavailable — semantic search disabled")
    embedder = None

mcp = FastMCP("ScreenMind")


# ═══════════════════════════════════════════════════════════════════════
#  TOOLS
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
def search_screen(query: str, limit: int = 10) -> str:
    """
    Search your screen history using natural language.
    Finds activities matching the query using semantic similarity and keyword matching.
    Use this when the user asks about something they saw, did, or worked on.

    Args:
        query: Natural language search query (e.g. "discord messages from aachii", "python code I was writing")
        limit: Maximum number of results to return (default 10)
    """
    conn = db._get_conn()

    results = []
    seen_ids = set()

    # 1. Semantic search (if embedder available)
    if embedder:
        rows = conn.execute(
            """
            SELECT id, timestamp, app_name, category, summary, details,
                   visible_text, bookmarked, embedding, organized_text
            FROM activities
            WHERE status = 'ok' AND embedding IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT 500
            """,
        ).fetchall()

        activities_data = []
        embeddings_list = []

        for row in rows:
            d = dict(row)
            emb = db._decode_embedding(d.get("embedding"))
            if emb:
                d.pop("embedding", None)
                activities_data.append(d)
                embeddings_list.append(emb)

        if embeddings_list:
            matches = embedder.search(query, embeddings_list, top_k=limit)
            for idx, score in matches:
                item = activities_data[idx]
                results.append({
                    "id": item["id"],
                    "timestamp": item["timestamp"],
                    "app": item["app_name"],
                    "category": item["category"],
                    "summary": item["summary"],
                    "details": item["details"],
                    "organized_text": (item.get("organized_text") or "")[:500],
                    "bookmarked": bool(item.get("bookmarked")),
                    "relevance": round(score, 3),
                    "match": "semantic",
                })
                seen_ids.add(item["id"])

    # 2. FTS5 keyword fallback
    try:
        # Escape FTS5 special characters by wrapping in double quotes
        fts_query = '"' + query.replace('"', '""') + '"'
        fts_rows = conn.execute(
            """
            SELECT a.id, a.timestamp, a.app_name, a.category, a.summary,
                   a.details, a.organized_text, a.bookmarked
            FROM activities_fts fts
            JOIN activities a ON a.id = fts.rowid
            WHERE activities_fts MATCH ? AND a.status = 'ok'
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, limit),
        ).fetchall()

        for row in fts_rows:
            d = dict(row)
            if d["id"] not in seen_ids:
                results.append({
                    "id": d["id"],
                    "timestamp": d["timestamp"],
                    "app": d["app_name"],
                    "category": d["category"],
                    "summary": d["summary"],
                    "details": d["details"],
                    "organized_text": (d.get("organized_text") or "")[:500],
                    "bookmarked": bool(d.get("bookmarked")),
                    "relevance": 0.5,
                    "match": "keyword",
                })
                seen_ids.add(d["id"])
    except Exception:
        pass

    results.sort(key=lambda x: x["relevance"], reverse=True)
    results = results[:limit]

    if not results:
        return json.dumps({"message": f"No results found for '{query}'.", "count": 0})

    return json.dumps({"query": query, "count": len(results), "results": results}, indent=2)


@mcp.tool()
def get_recent_activity(count: int = 10) -> str:
    """
    Get the most recent screen activities.
    Use this when the user asks "what was I just doing?", "what's on my screen?",
    or wants recent context about their work.

    Args:
        count: Number of recent activities to return (default 10, max 50)
    """
    count = min(count, 50)
    conn = db._get_conn()

    rows = conn.execute(
        """
        SELECT id, timestamp, app_name, category, summary, details,
               organized_text, bookmarked, mood
        FROM activities
        WHERE status = 'ok'
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (count,),
    ).fetchall()

    activities = []
    for row in rows:
        d = dict(row)
        activities.append({
            "id": d["id"],
            "timestamp": d["timestamp"],
            "app": d["app_name"],
            "category": d["category"],
            "summary": d["summary"],
            "details": d["details"],
            "organized_text": (d.get("organized_text") or "")[:500],
            "bookmarked": bool(d.get("bookmarked")),
        })

    if not activities:
        return json.dumps({"message": "No recent activities found.", "count": 0})

    return json.dumps({"count": len(activities), "activities": activities}, indent=2)


@mcp.tool()
def get_activity_by_time(
    date_str: str,
    start_hour: Optional[int] = None,
    end_hour: Optional[int] = None,
) -> str:
    """
    Get activities for a specific date and optional time range.
    Use this when the user asks about a specific day or time period.

    Args:
        date_str: Date in YYYY-MM-DD format (e.g. "2026-05-15")
        start_hour: Optional start hour (0-23) to filter by time range
        end_hour: Optional end hour (0-23) to filter by time range
    """
    # Validate date format
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return json.dumps({"error": f"Invalid date format '{date_str}'. Use YYYY-MM-DD (e.g. '2026-05-15')."})

    if start_hour is not None and not (0 <= start_hour <= 23):
        return json.dumps({"error": "start_hour must be 0-23"})
    if end_hour is not None and not (0 <= end_hour <= 23):
        return json.dumps({"error": "end_hour must be 0-23"})

    conn = db._get_conn()

    where = "status = 'ok' AND DATE(timestamp) = ?"
    params = [date_str]

    if start_hour is not None:
        where += " AND CAST(strftime('%H', timestamp) AS INTEGER) >= ?"
        params.append(start_hour)
    if end_hour is not None:
        where += " AND CAST(strftime('%H', timestamp) AS INTEGER) <= ?"
        params.append(end_hour)

    # FIXME: use parameterized where-clause builder instead of f-string interpolation.
    # Currently safe (where is only built from static strings + params), but fragile.
    rows = conn.execute(
        f"""
        SELECT id, timestamp, app_name, category, summary, details,
               organized_text, bookmarked
        FROM activities
        WHERE {where}
        ORDER BY timestamp ASC
        LIMIT 100
        """,
        params,
    ).fetchall()

    activities = []
    for row in rows:
        d = dict(row)
        activities.append({
            "id": d["id"],
            "timestamp": d["timestamp"],
            "app": d["app_name"],
            "category": d["category"],
            "summary": d["summary"],
            "details": d["details"],
            "organized_text": (d.get("organized_text") or "")[:300],
            "bookmarked": bool(d.get("bookmarked")),
        })

    if not activities:
        return json.dumps({"message": f"No activities found for {date_str}.", "count": 0})

    # Build summary of apps and categories
    apps = list(set(a["app"] for a in activities if a["app"]))
    cats = list(set(a["category"] for a in activities if a["category"]))

    return json.dumps({
        "date": date_str,
        "count": len(activities),
        "apps_used": apps,
        "categories": cats,
        "time_range": f"{activities[0]['timestamp']} to {activities[-1]['timestamp']}",
        "activities": activities,
    }, indent=2)


@mcp.tool()
def get_daily_summary(date_str: Optional[str] = None) -> str:
    """
    Get the AI-generated daily summary and standup notes for a date.
    Use this when the user asks for a summary of their day or standup notes.

    Args:
        date_str: Date in YYYY-MM-DD format. Defaults to today.
    """
    if not date_str:
        date_str = date.today().isoformat()

    summary_data = db.get_daily_summary(date_str)
    if not summary_data:
        return json.dumps({
            "message": f"No summary available for {date_str}. The user may need to generate one from the ScreenMind dashboard first.",
            "date": date_str,
        })

    return json.dumps({
        "date": date_str,
        "summary": summary_data.get("summary", ""),
        "standup": summary_data.get("standup", ""),
        "created_at": summary_data.get("created_at", ""),
    }, indent=2)


@mcp.tool()
def capture_now() -> str:
    """
    Trigger an instant screenshot capture.
    The screenshot will be analyzed by Gemma and added to the timeline.
    Requires the ScreenMind app to be running.
    """
    import urllib.request
    import urllib.error

    # 0.0.0.0/:: are listen addresses, not connect addresses
    host = "127.0.0.1" if settings.api_host in ("0.0.0.0", "::") else settings.api_host

    try:
        req = urllib.request.Request(
            f"http://{host}:{settings.api_port}/api/capture/bookmark",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.dumps({"status": "captured", "message": "Screenshot captured and queued for analysis."})
    except urllib.error.URLError:
        return json.dumps({
            "status": "error",
            "message": "Could not reach ScreenMind server. Make sure the app is running (screenmind).",
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool()
def get_stats() -> str:
    """
    Get overall statistics about the user's screen history.
    Use this to understand how much data is available and what the user has been doing.
    """
    today = date.today().isoformat()
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    stats = db.get_stats(date_from=week_ago, date_to=today)
    return json.dumps(stats, indent=2)


@mcp.tool()
def search_audio(query: str, limit: int = 10) -> str:
    """
    Search meeting transcripts and audio recordings.
    Use this when the user asks about something said in a meeting, call, or conversation.

    Args:
        query: Search query (e.g. "budget discussion", "action items from standup")
        limit: Maximum number of results to return (default 10)
    """
    conn = db._get_conn()

    try:
        # Escape LIKE wildcards in user query
        escaped = query.replace("%", "\\%").replace("_", "\\_")
        rows = conn.execute(
            """
            SELECT id, start_time, end_time, app_name, duration_minutes,
                   transcript, summary
            FROM meetings
            WHERE transcript LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\'
            ORDER BY start_time DESC
            LIMIT ?
            """,
            (f"%{escaped}%", f"%{escaped}%", limit),
        ).fetchall()
    except Exception:
        return json.dumps({"message": "Meetings table not available.", "count": 0})

    if not rows:
        return json.dumps({"message": f"No meeting transcripts matching '{query}'.", "count": 0})

    results = []
    for row in rows:
        d = dict(row)
        transcript = d.get("transcript") or ""
        # Extract matching snippet
        q_lower = query.lower()
        idx = transcript.lower().find(q_lower)
        if idx >= 0:
            start = max(0, idx - 100)
            end = min(len(transcript), idx + len(query) + 100)
            snippet = ("..." if start > 0 else "") + transcript[start:end] + ("..." if end < len(transcript) else "")
        else:
            snippet = transcript[:300]

        results.append({
            "meeting_id": d["id"],
            "start_time": d["start_time"],
            "end_time": d.get("end_time"),
            "app": d.get("app_name") or "Meeting",
            "duration_minutes": d.get("duration_minutes"),
            "summary": d.get("summary") or "",
            "transcript_snippet": snippet,
        })

    return json.dumps({"query": query, "count": len(results), "results": results}, indent=2)


@mcp.tool()
def get_screenshot(activity_id: int) -> str:
    """
    Get the file path to a screenshot for a specific activity.
    Use this when the user wants to see what their screen looked like at a specific time.
    The returned path can be used to view or reference the image.

    Args:
        activity_id: The activity ID (from search or timeline results)
    """
    from pathlib import Path
    conn = db._get_conn()
    row = conn.execute(
        "SELECT screenshot_path FROM activities WHERE id = ?",
        (activity_id,),
    ).fetchone()

    if not row or not row["screenshot_path"]:
        return json.dumps({"error": f"No screenshot found for activity {activity_id}."})

    filepath = Path(row["screenshot_path"]).resolve()

    # Validate path is within the screenshots directory
    try:
        filepath.relative_to(settings.screenshots_dir.resolve())
    except ValueError:
        return json.dumps({"error": f"Screenshot path is outside the data directory."})

    if not filepath.exists():
        return json.dumps({"error": f"Screenshot file missing for activity {activity_id}."})

    return json.dumps({
        "activity_id": activity_id,
        "screenshot_path": str(filepath),
        "size_kb": round(filepath.stat().st_size / 1024, 1),
    })


# ═══════════════════════════════════════════════════════════════════════
#  RESOURCES
# ═══════════════════════════════════════════════════════════════════════


@mcp.resource("screenmind://status")
def get_status() -> str:
    """Current ScreenMind system status and configuration."""
    return json.dumps({
        "model": settings.active_model,
        "capture_interval": settings.capture_interval,
        "performance_mode": settings.performance_mode,
        "analysis_mode": settings.analysis_mode,
        "capture_active_monitor": settings.capture_active_monitor,
        "data_path": str(settings.data_path),
    }, indent=2)


# ═══════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Restore real stdout for MCP protocol
    sys.stdout = _real_stdout
    logger.info("ScreenMind MCP server starting (stdio transport)...")
    mcp.run(transport="stdio")
