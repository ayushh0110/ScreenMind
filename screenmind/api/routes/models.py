"""Model management routes — list, download, switch models via model_manager."""

import asyncio
import threading

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from screenmind.config import settings
from screenmind.engine import model_manager

router = APIRouter(prefix="/api/models", tags=["models"])

_EXTERNAL_ERROR = (
    "llama-server is running outside ScreenMind. Stop it (or point "
    "LLAMA_SERVER_HOST elsewhere) to let ScreenMind start and switch models."
)


async def _external_in_use() -> bool:
    """Fresh check (off the event loop) — the server may have just stopped."""
    return await asyncio.to_thread(model_manager.sync_external_server)


@router.get("")
async def list_models():
    """List available models with download status."""
    models = model_manager.list_models()
    active = model_manager.get_active_model() or settings.active_model
    top_tier = max(m["tier"] for m in models) if models else 0
    active_tier = next((m["tier"] for m in models if m["key"] == active), 0)

    return {
        "models": models,
        "active": active,
        "is_top_model": active_tier >= top_tier,
    }


@router.post("/pull")
async def pull_model(request: Request):
    """
    Start downloading a model GGUF, then auto-switch and start server.

    Returns 202 immediately — work runs in a background thread.
    Frontend polls /api/status to track progress. (#1)
    """
    body = await request.json()
    key = body.get("tag", "") or body.get("key", "")
    quant = body.get("quant")  # optional: selected variant from dropdown

    info = model_manager.get_model_info(key)
    if not info:
        return JSONResponse({"error": "Unknown model"}, status_code=400)

    # Check if download/lifecycle is already in progress (single-flight)
    dl_state = model_manager.get_download_state()
    if dl_state["active"]:
        return JSONResponse(
            {"error": f"Download already in progress: {dl_state['model']}"},
            status_code=409,
        )

    # Fire-and-forget in a background thread — do NOT block the event loop
    threading.Thread(
        target=model_manager.download_and_start,
        args=(key,),
        kwargs={"quant": quant},
        daemon=True,
    ).start()

    return JSONResponse({"status": "started", "key": key}, status_code=202)


@router.get("/download-progress")
async def download_progress():
    """Get current download state for frontend polling."""
    return model_manager.get_download_state()


@router.post("/switch")
async def switch_model(request: Request):
    """Switch the active model (restarts llama-server)."""
    body = await request.json()
    key = body.get("tag", "") or body.get("key", "")

    info = model_manager.get_model_info(key)
    if not info:
        return JSONResponse({"error": "Unknown model"}, status_code=400)

    # Refuse if a lifecycle is already in progress (single-flight)
    dl_state = model_manager.get_download_state()
    if dl_state["active"]:
        return JSONResponse(
            {"error": f"Lifecycle in progress: {dl_state['model']}"},
            status_code=409,
        )
    if await _external_in_use():
        return JSONResponse({"error": _EXTERNAL_ERROR}, status_code=409)

    # Run in background thread to avoid blocking (#1 pattern)
    threading.Thread(
        target=model_manager.switch_model,
        args=(key,),
        daemon=True,
    ).start()

    return JSONResponse({"status": "switching", "key": key}, status_code=202)


@router.post("/restart")
async def restart_model_server():
    """
    Force-restart the server with the current active model.
    Used by the Retry button — guarantees a real restart regardless of active key. (#5)
    """
    if await _external_in_use():
        return JSONResponse({"error": _EXTERNAL_ERROR}, status_code=409)
    threading.Thread(
        target=model_manager.restart_server,
        daemon=True,
    ).start()

    return JSONResponse({"status": "restarting"}, status_code=202)


@router.post("/cancel")
async def cancel_download():
    """Cancel an active model download."""
    cancelled = model_manager.cancel_download()
    if cancelled:
        return JSONResponse({"status": "cancelled"})
    return JSONResponse({"error": "No active download to cancel"}, status_code=400)


@router.post("/variant")
async def set_variant(request: Request):
    """Change selected variant for a model. Restarts server if model is active."""
    body = await request.json()
    key = body.get("key", "")
    quant = body.get("quant", "")

    info = model_manager.get_model_info(key)
    if not info:
        return JSONResponse({"error": "Unknown model"}, status_code=400)
    if not any(v["quant"] == quant for v in info.get("variants", [])):
        return JSONResponse({"error": "Unknown variant"}, status_code=400)

    # Save preference
    variants = dict(settings.model_variants)
    variants[key] = quant
    settings.save_runtime_overrides({"model_variants": variants})

    # If this is the active model AND new variant is downloaded → restart
    # (never an external server — the preference applies once we manage it)
    if (model_manager.get_active_model() == key
            and model_manager.is_variant_downloaded(key, quant)
            and not model_manager.is_external_server()):
        threading.Thread(target=model_manager.restart_server, daemon=True).start()

    return JSONResponse({"status": "ok"})


@router.post("/delete")
async def delete_model_endpoint(request: Request):
    """Delete a specific variant or all variants of a model."""
    body = await request.json()
    key = body.get("key", "")
    quant = body.get("quant")  # optional — if omitted, delete all variants

    if quant:
        result = model_manager.delete_variant(key, quant)
    else:
        result = model_manager.delete_model(key)

    status_code = 200 if result.get("ok") else 409
    return JSONResponse(result, status_code=status_code)
