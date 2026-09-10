"""
Webhook Integration (v3)
- Named webhook profiles (default + extras)
- Persistent delivery log (SQLite, capped at 200)
- ThreadPoolExecutor(3) for fire_all/send_to_hook
- fire() kept backward-compatible (raw threads)
- Retry once on failure (after 5s)
- Custom headers + HMAC signing
"""

import logging
import hashlib
import hmac
import json
import sqlite3
import threading
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from screenmind.config import settings

logger = logging.getLogger("screenmind.integrations.webhooks")


# ── Delivery Log (persistent SQLite) ────────────────────────────────────
# Standalone DB at ~/.screenmind/webhook_log.db — avoids coupling to database.py

_log_local = threading.local()
_LOG_MAX = 200


def _get_log_conn() -> sqlite3.Connection:
    """Get a thread-local connection to the webhook delivery log DB."""
    if not hasattr(_log_local, "conn") or _log_local.conn is None:
        db_path = settings.data_path / "webhook_log.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                hook_name TEXT NOT NULL DEFAULT 'default',
                event TEXT NOT NULL,
                url TEXT NOT NULL,
                status TEXT NOT NULL,
                status_code INTEGER DEFAULT 0,
                error TEXT DEFAULT '',
                attempt INTEGER DEFAULT 1
            )
        """)
        conn.commit()
        _log_local.conn = conn
    return _log_local.conn


# Keep in-memory deque for backward compat (tests import it directly)
from collections import deque
_delivery_log = deque(maxlen=20)
_log_lock = threading.Lock()


def get_delivery_log(limit: int = 50) -> list:
    """Return the delivery log from SQLite (newest first). Falls back to in-memory."""
    try:
        conn = _get_log_conn()
        rows = conn.execute(
            "SELECT * FROM deliveries ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        # Fallback to in-memory
        with _log_lock:
            return list(reversed(_delivery_log))


def _log_delivery(url: str, event: str, status: str, status_code: int = 0,
                   error: str = "", attempt: int = 1, hook_name: str = "default"):
    """Record a delivery attempt to both SQLite and in-memory log."""
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "hook_name": hook_name,
        "url": url[:80],
        "event": event,
        "status": status,
        "status_code": status_code,
        "error": error[:120] if error else "",
        "attempt": attempt,
    }

    # In-memory (backward compat)
    with _log_lock:
        _delivery_log.append(entry)

    # Persistent SQLite
    try:
        conn = _get_log_conn()
        conn.execute(
            "INSERT INTO deliveries (timestamp, hook_name, event, url, status, status_code, error, attempt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (entry["timestamp"], hook_name, event, url[:80], status, status_code, entry["error"], attempt),
        )
        # Auto-prune beyond max
        conn.execute(
            "DELETE FROM deliveries WHERE id NOT IN (SELECT id FROM deliveries ORDER BY id DESC LIMIT ?)",
            (_LOG_MAX,),
        )
        conn.commit()
    except Exception as e:
        logger.debug(f"Delivery log write failed: {e}")


# ── Thread Pool ─────────────────────────────────────────────────────────
# Shared pool for fire_all() and send_to_hook() — caps concurrent deliveries

_pool = ThreadPoolExecutor(max_workers=3)


# ── Hook helpers ────────────────────────────────────────────────────────

def _get_extra_hooks() -> list:
    """Parse the webhook_extra JSON field from settings into a list of hook dicts."""
    try:
        hooks = json.loads(settings.webhook_extra)
        if isinstance(hooks, list):
            return hooks
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _get_hook_by_name(name: str) -> "dict | None":
    """Look up a named hook. 'default' returns the main webhook settings."""
    if name == "default":
        if not settings.webhook_url:
            return None
        return {
            "name": "default",
            "url": settings.webhook_url,
            "events": settings.webhook_events,
            "secret": settings.webhook_secret,
            "headers": settings.webhook_headers,
            "enabled": settings.webhook_enabled,
        }
    for hook in _get_extra_hooks():
        if hook.get("name") == name:
            return hook
    return None


# ── Core (backward compat) ──────────────────────────────────────────────

def fire(event: str, data: dict, urls: str, secret: str = "", enabled_events: str = "", headers: str = "") -> bool:
    """
    Fire webhooks for an event. Non-blocking (runs in a thread).
    Supports multiple URLs (comma-separated).

    BACKWARD COMPAT: kept for existing tests. New code should use fire_all().

    Args:
        event: Event type (daily_summary, bookmark, meeting_end, capture_milestone).
        data: Event-specific payload data.
        urls: Comma-separated webhook target URLs.
        secret: Optional HMAC-SHA256 secret for payload signing.
        enabled_events: Comma-separated list of enabled event types.
        headers: Optional custom headers as "Key: Value" lines (newline-separated).

    Returns:
        True if at least one webhook was queued.
    """
    if not urls:
        return False

    # Check if this event type is enabled
    if enabled_events:
        allowed = [e.strip() for e in enabled_events.split(",")]
        if event not in allowed:
            return False

    # Build a human-readable summary for platforms that use 'content' (Discord)
    _summary = data.get("summary") or data.get("message") or data.get("keyword") or event
    _content = f"**ScreenMind — {event}**\n{_summary[:1800]}"

    payload = {
        "event": event,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source": "screenmind",
        "data": data,
        "text": _content,
        "content": _content,
    }

    # Parse custom headers
    custom_headers = _parse_headers(headers)

    # Fire to each URL in background (raw threads for backward compat with tests)
    url_list = [u.strip() for u in urls.split(",") if u.strip()]
    for url in url_list:
        thread = threading.Thread(
            target=_send_with_retry, args=(url, payload, secret, custom_headers, event), daemon=True
        )
        thread.start()

    return True


# ── New: fire_all + send_to_hook ────────────────────────────────────────

def fire_all(event: str, data: dict) -> int:
    """
    Fire an event to ALL enabled hooks (default + extras) where the event is allowed.
    Uses ThreadPoolExecutor for bounded concurrency.

    Returns:
        Number of hooks that were queued for delivery.
    """
    queued = 0

    # Build human-readable content
    _summary = data.get("summary") or data.get("message") or data.get("keyword") or event
    _content = f"**ScreenMind — {event}**\n{_summary[:1800]}"
    payload = {
        "event": event,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source": "screenmind",
        "data": data,
        "text": _content,
        "content": _content,
    }

    # Collect all hooks to fire
    hooks_to_fire = []

    # Default hook
    if settings.webhook_enabled and settings.webhook_url:
        events_list = [e.strip() for e in settings.webhook_events.split(",") if e.strip()]
        if not events_list or event in events_list:
            for url in [u.strip() for u in settings.webhook_url.split(",") if u.strip()]:
                hooks_to_fire.append({
                    "name": "default",
                    "url": url,
                    "secret": settings.webhook_secret,
                    "headers": _parse_headers(settings.webhook_headers),
                })

    # Extra hooks (each has its own enabled flag)
    for hook in _get_extra_hooks():
        if not hook.get("enabled", True):
            continue
        if not hook.get("url"):
            continue
        hook_events = [e.strip() for e in hook.get("events", "").split(",") if e.strip()]
        if hook_events and event not in hook_events:
            continue
        for url in [u.strip() for u in hook["url"].split(",") if u.strip()]:
            hooks_to_fire.append({
                "name": hook.get("name", "extra"),
                "url": url,
                "secret": hook.get("secret", ""),
                "headers": _parse_headers(hook.get("headers", "")),
            })

    # Submit to thread pool
    for h in hooks_to_fire:
        _pool.submit(_send_with_retry_named, h["url"], payload, h["secret"], h["headers"], event, h["name"])
        queued += 1

    return queued


def send_to_hook(hook_name: str, agent_name: str, output: str) -> bool:
    """
    Send agent output to a specific named hook. Used by agent_runner.

    Args:
        hook_name: Hook name ('default' or a named extra hook).
        agent_name: Name of the agent that produced the output.
        output: The agent's text output.

    Returns:
        True if the hook was found and delivery was queued.
    """
    hook = _get_hook_by_name(hook_name)
    if not hook:
        logger.warning(f"Hook '{hook_name}' not found, skipping agent output push")
        return False
    if not hook.get("enabled", True):
        logger.debug(f"Hook '{hook_name}' is disabled, skipping")
        return False
    if not hook.get("url"):
        logger.warning(f"Hook '{hook_name}' has no URL configured")
        return False

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    _trunc = output[:1900]  # Discord content limit is 2000; leave room for header
    payload = {
        "event": "agent_output",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source": "screenmind",
        "agent": agent_name,
        "data": {"agent": agent_name, "output": _trunc},
        "text": f"*{agent_name}* — {date_str}\n\n{_trunc}",
        "content": f"**{agent_name}** — {date_str}\n\n{_trunc}",
    }

    secret = hook.get("secret", "")
    custom_headers = _parse_headers(hook.get("headers", ""))

    for url in [u.strip() for u in hook["url"].split(",") if u.strip()]:
        _pool.submit(_send_with_retry_named, url, payload, secret, custom_headers, "agent_output", hook_name)

    return True


# ── Sending ─────────────────────────────────────────────────────────────

def _parse_headers(headers_str: str) -> dict:
    """Parse "Key: Value" newline-separated string into a dict."""
    result = {}
    if not headers_str:
        return result
    for line in headers_str.split("\n"):
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


def _send_with_retry(url: str, payload: dict, secret: str, custom_headers: dict, event: str):
    """Send webhook with one retry on failure. Used by fire() (backward compat)."""
    success = _send(url, payload, secret, custom_headers, event, attempt=1)
    if not success:
        time.sleep(5)
        _send(url, payload, secret, custom_headers, event, attempt=2)


def _send_with_retry_named(url: str, payload: dict, secret: str, custom_headers: dict,
                            event: str, hook_name: str = "default"):
    """Send webhook with one retry. Logs with hook_name. Used by fire_all()/send_to_hook()."""
    success = _send(url, payload, secret, custom_headers, event, attempt=1, hook_name=hook_name)
    if not success:
        time.sleep(5)
        _send(url, payload, secret, custom_headers, event, attempt=2, hook_name=hook_name)


def _send(url: str, payload: dict, secret: str, custom_headers: dict,
          event: str, attempt: int = 1, hook_name: str = "default") -> bool:
    """Actually send the webhook. Returns True on success."""
    try:
        body = json.dumps(payload).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ScreenMind-Webhook/2.0",
        }

        # HMAC signing if secret is provided
        if secret:
            signature = hmac.HMAC(
                secret.encode("utf-8"),
                body,
                hashlib.sha256,
            ).hexdigest()
            headers["X-ScreenMind-Signature"] = f"sha256={signature}"

        # Merge custom headers
        headers.update(custom_headers)

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            status_code = resp.status
            _log_delivery(url, event, "ok", status_code=status_code, attempt=attempt, hook_name=hook_name)
            label = f"(retry #{attempt})" if attempt > 1 else ""
            logger.info(f"{event} → {url[:50]} → {status_code} {label}")
            return True

    except urllib.error.HTTPError as e:
        _log_delivery(url, event, "failed", status_code=e.code, error=str(e), attempt=attempt, hook_name=hook_name)
        logger.error(f"Failed ({event} → {url[:50]}): HTTP {e.code}")
        return False
    except urllib.error.URLError as e:
        _log_delivery(url, event, "failed", error=str(e.reason), attempt=attempt, hook_name=hook_name)
        logger.error(f"Failed ({event} → {url[:50]}): {e.reason}")
        return False
    except Exception as e:
        _log_delivery(url, event, "failed", error=str(e), attempt=attempt, hook_name=hook_name)
        logger.error(f"Error ({event} → {url[:50]}): {e}")
        return False


def test_webhook(url: str, secret: str = "", headers: str = "") -> dict:
    """Send a test ping to the webhook URL. Returns status dict."""
    if not url:
        return {"ok": False, "error": "No URL provided"}

    payload = {
        "event": "test",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source": "screenmind",
        "data": {"message": "This is a test webhook from ScreenMind."},
        "text": "✅ ScreenMind webhook test successful!",
        "content": "✅ ScreenMind webhook test successful!",
    }

    custom_headers = _parse_headers(headers)

    try:
        body = json.dumps(payload).encode("utf-8")
        req_headers = {
            "Content-Type": "application/json",
            "User-Agent": "ScreenMind-Webhook/2.0",
        }
        if secret:
            signature = hmac.HMAC(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
            req_headers["X-ScreenMind-Signature"] = f"sha256={signature}"
        req_headers.update(custom_headers)

        req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            _log_delivery(url, "test", "ok", status_code=resp.status)
            return {"ok": True, "status": resp.status}
    except Exception as e:
        _log_delivery(url, "test", "failed", error=str(e))
        return {"ok": False, "error": str(e)}
