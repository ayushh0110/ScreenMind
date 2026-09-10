"""Settings routes — get/update config, integration tests, webhook log."""

import json
import sys

from fastapi import APIRouter, Request

from screenmind.config import settings

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings")
async def get_settings():
    """Return current resource management settings."""
    return {
        "capture_interval": settings.capture_interval,
        "performance_mode": settings.performance_mode,
        "context_window": settings.context_window,
        "kv_cache_quant": settings.kv_cache_quant,
        "flash_attention": settings.flash_attention,
        "analysis_mode": settings.analysis_mode,
        "auto_pause_heavy_apps": settings.auto_pause_heavy_apps,
        "heavy_apps": settings.heavy_apps,
        "defer_analysis": settings.defer_analysis,
        "meeting_transcription": settings.meeting_transcription,
        "meeting_apps": settings.meeting_apps,
        "retention_days": settings.retention_days,
        "ollama_model": settings.ollama_model,
        "obsidian_enabled": settings.obsidian_enabled,
        "obsidian_vault_path": settings.obsidian_vault_path,
        "notion_enabled": settings.notion_enabled,
        "notion_token": settings.notion_token,
        "notion_database_id": settings.notion_database_id,
        "webhook_enabled": settings.webhook_enabled,
        "webhook_url": settings.webhook_url,
        "webhook_events": settings.webhook_events,
        "webhook_secret": settings.webhook_secret,
        "webhook_headers": settings.webhook_headers,
        "webhook_extra": json.loads(settings.webhook_extra) if settings.webhook_extra else [],
        "smart_notifications": settings.smart_notifications,
        "distraction_minutes": settings.distraction_minutes,
        "break_reminder_minutes": settings.break_reminder_minutes,
        "auto_bookmark": settings.auto_bookmark,
        "auto_bookmark_keywords": settings.auto_bookmark_keywords,
        "agents_enabled": settings.agents_enabled,
        "agents_auto_run_python": settings.agents_auto_run_python,
        "sensitive_filter_enabled": settings.sensitive_filter_enabled,
        "sensitive_filter_types": settings.sensitive_filter_types,
        "dashboard_pin_set": bool(settings.dashboard_pin_hash),
        "dashboard_lock_timeout": settings.dashboard_lock_timeout,
        "encryption_enabled": settings.encryption_enabled,
        "bookmark_hotkey": settings.bookmark_hotkey,
        "pause_hotkey": settings.pause_hotkey,
        "voice_hotkey": settings.voice_hotkey,
        "capture_active_monitor": settings.capture_active_monitor,
    }


@router.post("/settings")
async def update_settings(request: Request):
    """Update resource management settings (persists to settings.json)."""
    body = await request.json()
    # Serialize webhook_extra list to JSON string for storage
    if "webhook_extra" in body and isinstance(body["webhook_extra"], list):
        body["webhook_extra"] = json.dumps(body["webhook_extra"])
    settings.save_runtime_overrides(body)
    return {
        "status": "saved",
        "capture_interval": settings.capture_interval,
        "performance_mode": settings.performance_mode,
        "context_window": settings.context_window,
        "kv_cache_quant": settings.kv_cache_quant,
        "flash_attention": settings.flash_attention,
        "analysis_mode": settings.analysis_mode,
        "auto_pause_heavy_apps": settings.auto_pause_heavy_apps,
        "heavy_apps": settings.heavy_apps,
        "defer_analysis": settings.defer_analysis,
        "meeting_transcription": settings.meeting_transcription,
        "meeting_apps": settings.meeting_apps,
        "retention_days": settings.retention_days,
        "ollama_model": settings.ollama_model,
        "obsidian_enabled": settings.obsidian_enabled,
        "obsidian_vault_path": settings.obsidian_vault_path,
        "notion_enabled": settings.notion_enabled,
        "notion_token": settings.notion_token,
        "notion_database_id": settings.notion_database_id,
        "webhook_enabled": settings.webhook_enabled,
        "webhook_url": settings.webhook_url,
        "webhook_events": settings.webhook_events,
        "webhook_secret": settings.webhook_secret,
        "webhook_headers": settings.webhook_headers,
        "webhook_extra": json.loads(settings.webhook_extra) if settings.webhook_extra else [],
        "smart_notifications": settings.smart_notifications,
        "distraction_minutes": settings.distraction_minutes,
        "break_reminder_minutes": settings.break_reminder_minutes,
        "auto_bookmark": settings.auto_bookmark,
        "auto_bookmark_keywords": settings.auto_bookmark_keywords,
        "agents_enabled": settings.agents_enabled,
        "agents_auto_run_python": settings.agents_auto_run_python,
        "sensitive_filter_enabled": settings.sensitive_filter_enabled,
        "sensitive_filter_types": settings.sensitive_filter_types,
        "dashboard_pin_set": bool(settings.dashboard_pin_hash),
        "dashboard_lock_timeout": settings.dashboard_lock_timeout,
        "encryption_enabled": settings.encryption_enabled,
        "bookmark_hotkey": settings.bookmark_hotkey,
        "pause_hotkey": settings.pause_hotkey,
        "voice_hotkey": settings.voice_hotkey,
        "capture_active_monitor": settings.capture_active_monitor,
    }


@router.post("/integrations/test")
async def test_integration(request: Request):
    """Test an integration connection (Notion or Webhook)."""
    body = await request.json()
    integration = body.get("type")

    if integration == "notion":
        from screenmind.integrations.notion import test_connection
        result = test_connection(
            body.get("token", settings.notion_token),
            body.get("database_id", settings.notion_database_id),
        )
        return result

    elif integration == "webhook":
        from screenmind.integrations.webhooks import test_webhook
        result = test_webhook(
            body.get("url", settings.webhook_url),
            body.get("secret", settings.webhook_secret),
            body.get("headers", settings.webhook_headers),
        )
        return result

    return {"ok": False, "error": "Unknown integration type"}


@router.get("/webhooks/log")
async def get_webhook_log():
    """Return the last 20 webhook deliveries."""
    from screenmind.integrations.webhooks import get_delivery_log
    return {"deliveries": get_delivery_log()}


@router.get("/startup/status")
async def get_startup_status():
    """Check if ScreenMind is registered in system startup."""
    from screenmind.startup import is_startup_installed
    return {"installed": is_startup_installed()}


@router.post("/startup/install")
async def install_startup_route():
    """Register ScreenMind to start at system login."""
    from screenmind.startup import install_startup
    ok = install_startup()
    return {"ok": ok, "message": "Registered in system startup" if ok else "Failed to register"}


@router.post("/startup/uninstall")
async def uninstall_startup_route():
    """Remove ScreenMind from system startup."""
    from screenmind.startup import uninstall_startup
    ok = uninstall_startup()
    return {"ok": ok, "message": "Removed from system startup" if ok else "Failed to remove"}


@router.post("/shutdown")
async def shutdown_server(request: Request):
    """Gracefully shut down ScreenMind. Restricted to localhost."""
    import asyncio
    import os
    import signal
    import logging

    # Security: only allow shutdown from localhost
    client_host = request.client.host if request.client else None
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Shutdown only allowed from localhost")

    logger = logging.getLogger("screenmind.api")
    logger.info("Shutdown requested via API")

    async def _delayed_shutdown():
        await asyncio.sleep(0.5)  # let the response reach the client
        # Use SIGINT for clean shutdown — allows uvicorn to run cleanup,
        # close DB connections, stop llama-server, flush logs, run atexit.
        if sys.platform == "win32":
            # Windows: SIGINT to self doesn't work reliably, use CTRL_C_EVENT
            os.kill(os.getpid(), signal.CTRL_C_EVENT)
        else:
            os.kill(os.getpid(), signal.SIGINT)

    asyncio.create_task(_delayed_shutdown())
    return {"ok": True, "message": "ScreenMind is shutting down..."}
