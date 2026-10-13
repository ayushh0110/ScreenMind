"""Capture control routes — pause, resume, incognito, status."""

import asyncio

from fastapi import APIRouter

from screenmind.api.dependencies import capture_worker, analysis_worker
from screenmind.engine import model_manager

router = APIRouter(prefix="/api", tags=["capture"])


@router.post("/capture/bookmark")
async def bookmark_capture():
    """Trigger an instant bookmarked screenshot capture."""
    if not capture_worker:
        return {"status": "error", "message": "Capture worker not available"}
    if not capture_worker.trigger_bookmark():
        return {"status": "error", "message": "Incognito mode is on — nothing is captured."}
    return {"status": "captured", "message": "Screenshot captured and bookmarked."}


@router.post("/capture/pause")
async def pause_capture():
    if capture_worker:
        capture_worker.pause(source="dashboard")
    return {"paused": True}


@router.post("/capture/resume")
async def resume_capture():
    if capture_worker:
        capture_worker.resume(source="dashboard")
    return {"paused": False}


@router.post("/incognito/toggle")
async def toggle_incognito():
    """Toggle incognito mode: pauses capture and stops meeting recording."""
    if not capture_worker:
        return {"error": "Capture worker not available"}
    enabled = not capture_worker.incognito
    # Turning it on may wait for an in-progress meeting recording to stop
    await asyncio.get_running_loop().run_in_executor(None, capture_worker.set_incognito, enabled)
    return {"incognito": enabled}


@router.get("/status")
async def get_status():
    """System status for the dashboard, including model/server state."""
    return {
        "status": "running",
        "capture": capture_worker.stats if capture_worker else {},
        "analysis": analysis_worker.stats if analysis_worker else {},
        "incognito": capture_worker.incognito if capture_worker else False,
        "model": model_manager.get_model_status(),
    }
