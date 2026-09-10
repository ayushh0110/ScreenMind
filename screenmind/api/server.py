"""
ScreenMind API Server
Creates the FastAPI app, mounts static files, and includes all route modules.
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from screenmind.config import settings
from screenmind.engine.embedder import Embedder
from screenmind.storage.database import Database

import logging
import screenmind.api.dependencies as deps

logger = logging.getLogger("screenmind.api.server")


class AuthMiddleware(BaseHTTPMiddleware):
    """PIN lock middleware — blocks API access if PIN is set and no valid session."""

    OPEN_PATHS = {"/", "/api/auth/verify", "/api/auth/status", "/api/auth/setup-complete", "/api/status"}
    OPEN_PREFIXES = ("/css/", "/js/", "/api/auth/")
    # Internal paths — only accessible from localhost (agents, MCP, SDK)
    LOCALHOST_ONLY_PREFIXES = ("/api/agents/sdk/", "/api/timeline")
    LOCALHOST_ONLY_PATHS = {"/api/capture/bookmark"}

    async def dispatch(self, request: Request, call_next):
        # No PIN set — everything is open
        if not settings.dashboard_pin_hash:
            return await call_next(request)

        path = request.url.path

        # Allow open paths (no auth required from anywhere)
        if path in self.OPEN_PATHS or any(path.startswith(p) for p in self.OPEN_PREFIXES):
            return await call_next(request)

        # Localhost-only paths — SDK, timeline, bookmark (agents/MCP use these internally)
        if path in self.LOCALHOST_ONLY_PATHS or any(path.startswith(p) for p in self.LOCALHOST_ONLY_PREFIXES):
            client_host = request.client.host if request.client else None
            if client_host in ("127.0.0.1", "::1"):
                return await call_next(request)
            return JSONResponse({"error": "unauthorized", "locked": True}, status_code=401)

        # Check session cookie
        token = request.cookies.get("screenmind_session")
        if deps.verify_session(token):
            return await call_next(request)

        # Blocked
        return JSONResponse({"error": "unauthorized", "locked": True}, status_code=401)


def create_app(database: Database, capture_worker=None, analysis_worker=None, embedder=None, audio_worker=None):
    """Create and configure the FastAPI application."""

    app = FastAPI(title="ScreenMind", version="0.1.1")

    # Add auth middleware
    app.add_middleware(AuthMiddleware)

    # Use provided embedder or create one
    if embedder is None:
        try:
            embedder = Embedder()
            embedder._ensure_model()
        except Exception:
            logger.warning("Embedder unavailable — search will be limited")

    # Initialize shared dependencies for all route modules
    deps.init(database, embedder, capture_worker, analysis_worker, audio_worker)

    # ── Static Files ─────────────────────────────────────────────────
    static_dir = Path(__file__).parent / "static"
    app.mount("/css", StaticFiles(directory=str(static_dir / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(static_dir / "js")), name="js")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return (static_dir / "index.html").read_text(encoding="utf-8")

    # ── Include Route Modules ────────────────────────────────────────
    from screenmind.api.routes.auth import router as auth_router
    from screenmind.api.routes.capture import router as capture_router
    from screenmind.api.routes.timeline import router as timeline_router
    from screenmind.api.routes.search import router as search_router
    from screenmind.api.routes.chat import router as chat_router
    from screenmind.api.routes.stats import router as stats_router
    from screenmind.api.routes.screenshots import router as screenshots_router
    from screenmind.api.routes.bookmarks import router as bookmarks_router
    from screenmind.api.routes.rewind import router as rewind_router
    from screenmind.api.routes.summary import router as summary_router
    from screenmind.api.routes.meetings import router as meetings_router
    from screenmind.api.routes.agents import router as agents_router
    from screenmind.api.routes.settings import router as settings_router
    from screenmind.api.routes.models import router as models_router
    from screenmind.api.routes.data import router as data_router
    from screenmind.api.routes.memos import router as memos_router
    app.include_router(auth_router)
    app.include_router(capture_router)
    app.include_router(timeline_router)
    app.include_router(search_router)
    app.include_router(chat_router)
    app.include_router(stats_router)
    app.include_router(screenshots_router)
    app.include_router(bookmarks_router)
    app.include_router(rewind_router)
    app.include_router(summary_router)
    app.include_router(meetings_router)
    app.include_router(agents_router)
    app.include_router(settings_router)
    app.include_router(models_router)
    app.include_router(data_router)
    app.include_router(memos_router)

    return app
