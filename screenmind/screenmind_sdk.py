"""
ScreenMind SDK
Helper module for Python plugin agents. Wraps the local REST API.

Usage in plugins:
    from screenmind.screenmind_sdk import get_recent_activity, notify, search
    from screenmind.screenmind_sdk import save_state, load_state, ask_gemma
"""

import logging
import json
import os
import re
import time
import threading
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("screenmind.sdk")


def _api_base() -> str:
    """Local API URL of the running ScreenMind app (follows api_host/api_port)."""
    from screenmind.config import settings
    # 0.0.0.0 / :: are listen addresses, not connect addresses
    host = "127.0.0.1" if settings.api_host in ("0.0.0.0", "::") else settings.api_host
    return f"http://{host}:{settings.api_port}"


# Thread-local storage for current agent context.
# Set by agent_runner before calling plugin's run().
_agent_context = threading.local()


def _get_current_agent() -> str:
    return getattr(_agent_context, "name", "unknown")


def _set_current_agent(name: str):
    _agent_context.name = name


# ── HTTP Helpers ─────────────────────────────────────────────────────

def _get(path: str) -> dict:
    """Make a GET request to the local API."""
    try:
        with urllib.request.urlopen(f"{_api_base()}{path}", timeout=15) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        logger.error(f"GET {path} failed: {e}")
        return {}
    except json.JSONDecodeError as e:
        logger.warning(f"GET {path} invalid JSON: {e}")
        return {}


def _post(path: str, data: dict = None) -> dict:
    """Make a POST request to the local API."""
    try:
        body = json.dumps(data or {}).encode("utf-8")
        req = urllib.request.Request(
            f"{_api_base()}{path}", data=body,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        logger.error(f"POST {path} failed: {e}")
        return {}
    except json.JSONDecodeError as e:
        logger.warning(f"POST {path} invalid JSON: {e}")
        return {}


# ── Agent Name Helpers ───────────────────────────────────────────────

def _sanitize_name(name: str) -> str:
    """Sanitize agent name for filesystem safety. Prevents path traversal."""
    return re.sub(r'[^a-zA-Z0-9_-]', '', name) or "unknown"


def _resolve_agent(agent_name: str = None) -> str:
    """Resolve agent name: explicit param > module global > 'unknown'."""
    name = agent_name or _get_current_agent() or "unknown"
    return _sanitize_name(name)


# ── Data Access (Original) ──────────────────────────────────────────

def get_recent_activity(minutes: int = 30, limit: int = 50) -> list:
    """Get recent screen activities.

    Args:
        minutes: Only return activities from the last N minutes
        limit: Max number of results

    Returns list of dicts with: id, timestamp, app_name, category, summary, details
    """
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()
    result = _get(f"/api/timeline?since={urllib.parse.quote(cutoff)}&limit={limit}")
    return result.get("activities", [])


def get_activities_by_date(date_str: str, limit: int = 200) -> list:
    """Get activities for a specific date (YYYY-MM-DD).

    Returns list of activity dicts.
    """
    result = _get(f"/api/timeline?date={date_str}&limit={limit}")
    return result.get("activities", [])


def search(query: str, limit: int = 10) -> list:
    """Semantic search across all screen history.

    Returns list of matching activities.
    """
    result = _get(f"/api/search?q={urllib.parse.quote(query)}&limit={limit}")
    return result.get("results", [])


def get_summary(date_str: str = None) -> str:
    """Get the daily summary for a date. Returns summary text."""
    path = "/api/summary"
    if date_str:
        path += f"?date={date_str}"
    result = _get(path)
    summary = result.get("summary", {})
    if isinstance(summary, dict):
        return summary.get("summary", "")
    return str(summary)


def get_stats() -> dict:
    """Get capture statistics. Returns dict with total_captures, etc."""
    return _get("/api/status")


def notify(title: str, message: str, color: str = "#8b5cf6"):
    """Show an overlay notification to the user."""
    try:
        from screenmind.ui.overlay import show_overlay_notification
        show_overlay_notification(title, message, duration=5.0, color=color)
    except Exception:
        logger.info(f"{title}: {message}")


def capture_now() -> dict:
    """Trigger an immediate screenshot capture."""
    return _post("/api/capture/bookmark")


def write_file(path: str, content: str):
    """Write content to a file (for Obsidian export, logs, etc.).

    Path is restricted to the ScreenMind data directory to prevent
    agents from writing arbitrary files on the filesystem.
    """
    from screenmind.config import settings
    resolved = Path(path).resolve()
    allowed = settings.data_path.resolve()
    if not resolved.is_relative_to(allowed):
        raise PermissionError(f"write_file blocked: path must be under {allowed}, got {resolved}")
    os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
    with open(resolved, "w", encoding="utf-8") as f:
        f.write(content)
    logger.debug(f"Wrote {len(content)} bytes to {resolved}")


# ── Data Access (New — Filtered Queries) ─────────────────────────────

def get_activities(
    date: str = None,
    app: str = None,
    category: str = None,
    url_contains: str = None,
    limit: int = 50,
) -> list:
    """Filtered activity query via SDK endpoint.

    Args:
        date: YYYY-MM-DD (default: today)
        app: Filter by app_name (e.g. "Microsoft Edge")
        category: Filter by category (e.g. "coding", "browsing")
        url_contains: Filter active_url containing this string (e.g. "github.com")
        limit: Max results (default 50)

    Returns: list of activity dicts with all fields including active_url, mood, etc.
    """
    params = [f"limit={limit}"]
    if date:
        params.append(f"date={date}")
    if app:
        params.append(f"app={urllib.parse.quote(app)}")
    if category:
        params.append(f"category={urllib.parse.quote(category)}")
    if url_contains:
        params.append(f"url_contains={urllib.parse.quote(url_contains)}")

    result = _get(f"/api/agents/sdk/activities?{'&'.join(params)}")
    return result.get("activities", [])


def get_urls_visited(date: str = None) -> list:
    """Get all unique URLs visited today (from active_url column).

    Returns: [{"url": "...", "app": "Edge", "timestamp": "...", "summary": "...", "count": 3}]
    Deduplicated by URL, sorted by frequency.
    """
    params = ["has_url=true", "limit=200"]
    if date:
        params.append(f"date={date}")

    result = _get(f"/api/agents/sdk/activities?{'&'.join(params)}")
    activities = result.get("activities", [])

    # Deduplicate by URL
    url_data = {}
    for a in activities:
        url = a.get("active_url", "")
        if not url:
            continue
        if url not in url_data:
            url_data[url] = {
                "url": url,
                "app": a.get("app_name", ""),
                "timestamp": a.get("timestamp", ""),
                "summary": a.get("summary", ""),
                "count": 0,
            }
        url_data[url]["count"] += 1

    # Sort by frequency
    return sorted(url_data.values(), key=lambda x: x["count"], reverse=True)


def get_meetings(date: str = None) -> list:
    """Get meetings for a date.

    Returns: list of meeting dicts with start_time, app_name, summary, duration, transcript.
    """
    target = date or str(datetime.now().date())
    result = _get(f"/api/meetings?date={target}")
    return result.get("meetings", [])


def get_app_usage(date: str = None) -> dict:
    """Get app usage breakdown for a date.

    Returns: {"Edge": {"captures": 18, "categories": ["browsing"]}, ...}
    Note: captures, NOT minutes. Multiply by capture_interval for rough time estimate.
    """
    target = date or str(datetime.now().date())
    activities = get_activities(date=target, limit=200)

    usage = {}
    for a in activities:
        app = a.get("app_name", "Unknown")
        if app not in usage:
            usage[app] = {"captures": 0, "categories": set()}
        usage[app]["captures"] += 1
        cat = a.get("category", "other")
        usage[app]["categories"].add(cat)

    # Convert sets to sorted lists for JSON serialization
    for app in usage:
        usage[app]["categories"] = sorted(usage[app]["categories"])

    return usage


# ── Persistent State ─────────────────────────────────────────────────

def _state_path(agent_name: str = None) -> Path:
    """Get the state file path for an agent. Path-traversal safe."""
    from screenmind.config import settings
    name = _resolve_agent(agent_name)
    state_dir = settings.data_path / "agents" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / f"{name}.json"


def _load_state_file(agent_name: str = None) -> dict:
    """Load full state dict from disk."""
    path = _state_path(agent_name)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_state_file(state: dict, agent_name: str = None):
    """Write full state dict to disk."""
    path = _state_path(agent_name)
    path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def save_state(key: str, value, agent_name: str = None):
    """Save a JSON-serializable value to persistent agent state.

    State is stored per-agent in ~/.screenmind/agents/state/{agent}.json.
    Agent names are sanitized to prevent path traversal.

    Args:
        key: State key (e.g. "todos", "last_run")
        value: Any JSON-serializable value
        agent_name: Optional explicit agent name (defaults to current agent)
    """
    state = _load_state_file(agent_name)
    state[key] = value
    _save_state_file(state, agent_name)


def load_state(key: str, default=None, agent_name: str = None):
    """Load a value from persistent agent state.

    Args:
        key: State key to load
        default: Value to return if key not found
        agent_name: Optional explicit agent name (defaults to current agent)

    Returns: The stored value, or default if not found.
    """
    state = _load_state_file(agent_name)
    return state.get(key, default)


def clear_state(key: str = None, agent_name: str = None):
    """Clear agent state — one key or all.

    Args:
        key: Specific key to clear. If None, clears all state.
        agent_name: Optional explicit agent name (defaults to current agent)
    """
    if key is None:
        # Clear all state
        path = _state_path(agent_name)
        if path.exists():
            path.unlink()
    else:
        state = _load_state_file(agent_name)
        state.pop(key, None)
        _save_state_file(state, agent_name)


# ── LLM Access ───────────────────────────────────────────────────────

def ask_gemma(prompt: str, include_recent: bool = False, max_tokens: int = 512) -> str:
    """Ask Gemma a question. Waits for GPU to be idle (up to 60s).

    Never cancels running screen analysis — waits or times out.
    On constrained hardware (≤4GB VRAM), this may be slow during active capture.
    Consider upgrading to 8GB+ VRAM for responsive agent inference.

    Args:
        prompt: The question/instruction for Gemma
        include_recent: If True, prepend recent activity summaries as context
        max_tokens: Max output tokens (default 512)

    Returns: Gemma's text response

    Raises: RuntimeError if LLM is busy for >60s
    """
    from screenmind.engine import llm_client

    # Optionally prepend recent activity context
    full_prompt = prompt
    if include_recent:
        try:
            activities = get_recent_activity(minutes=30, limit=10)
            if activities:
                ctx_lines = [f"- [{a.get('timestamp', '?')}] {a.get('app_name', '?')}: {a.get('summary', '')}"
                             for a in activities[:10]]
                full_prompt = f"Recent user activity:\n{''.join(ctx_lines[:5])}\n\n---\n\n{prompt}"
        except Exception:
            pass  # Proceed without context if API fails

    # Wait for LLM to be idle (never cancel running inference)
    deadline = time.time() + 60
    while time.time() < deadline:
        if not llm_client.is_inference_active():
            break
        time.sleep(2)
    else:
        raise RuntimeError(
            "LLM is busy with screen analysis. "
            "Try again later, or upgrade to 8GB+ VRAM for concurrent agent inference."
        )

    # Run inference
    try:
        return llm_client.generate(
            prompt=full_prompt,
            temperature=0.3,
            max_tokens=max_tokens,
        )
    except Exception as e:
        raise RuntimeError(f"Gemma inference failed: {e}")


# ── Utility ──────────────────────────────────────────────────────────

def get_output_dir(agent_name: str = None) -> Path:
    """Get the output directory for an agent. Creates it if needed.

    Returns: Path to ~/.screenmind/agents/output/{agent_name}/
    """
    from screenmind.config import settings
    name = _resolve_agent(agent_name)
    out_dir = settings.data_path / "agents" / "output" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir
