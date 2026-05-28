"""
ScreenMind — Main Entry Point
Starts all services: capture, analysis, API server.
Includes startup health checks and graceful error handling.
"""

import asyncio
import shutil
import signal
import sys

import threading

import uvicorn

from config import settings
from storage.database import Database
from engine.embedder import Embedder
from workers.capture_worker import CaptureWorker
from workers.analysis_worker import AnalysisWorker
from workers.audio_worker import AudioWorker
from capture.hotkey import HotkeyListener
from api.server import create_app


def check_llama_server() -> bool:
    """Check if llama-server is reachable and ready for inference."""
    from engine import llm_client

    status = llm_client.get_server_status()
    if status["status"] == "ok":
        print(f"[Health] OK - llama-server online at {settings.llama_server_host}")
        return True
    elif status["status"] == "unreachable":
        print(f"[Health] FAIL - Cannot reach llama-server at {settings.llama_server_host}")
        print(f"[Health]   Start it with: llama-server -hf unsloth/gemma-4-E2B-it-GGUF:Q4_K_M --mmproj-auto -ngl 99 --port {settings.llama_server_port}")
        return False
    else:
        print(f"[Health] WARN - llama-server issue: {status['detail']}")
        return False


def check_disk_space():
    """Warn if disk space is low."""
    try:
        usage = shutil.disk_usage(str(settings.data_path))
        free_gb = usage.free / (1024 ** 3)
        if free_gb < 1.0:
            print(f"[Health] WARN - Low disk space: {free_gb:.1f}GB free. ScreenMind needs space for screenshots.")
        else:
            print(f"[Health] OK - Disk space: {free_gb:.1f}GB free")
    except Exception:
        pass


def print_first_run_help():
    """Show helpful info on first run (no DB yet)."""
    if not settings.db_path.exists():
        print()
        print("  +==========================================+")
        print("  |  Welcome to ScreenMind -- First Run!     |")
        print("  +==========================================+")
        print("  |  Screenshots will be saved to:           |")
        print(f"  |    {str(settings.screenshots_dir)[:38]:<38} |")
        print("  |                                          |")
        print("  |  Press Ctrl+Shift+B to bookmark a moment |")
        print("  |  Open the dashboard to see your timeline |")
        print("  +==========================================+")
        print()


async def main():
    """Initialize and run all ScreenMind services."""

    print("=" * 60)
    print("  ScreenMind — Privacy-First Screen Activity Journal")
    print("  Powered by Gemma 4 E2B (100% Local)")
    print("=" * 60)
    print()

    # ── First-run experience ─────────────────────────────────────────
    settings.ensure_dirs()
    print_first_run_help()

    print(f"[Main] Data directory: {settings.data_path}")
    print(f"[Main] Capture interval: {settings.capture_interval}s")
    print(f"[Main] Model: {settings.active_model} ({settings.gemma_mode} mode)")
    if settings.blocked_apps_list:
        print(f"[Main] Privacy zones: {', '.join(settings.blocked_apps_list)}")
    if settings.gemma_mode == "api":
        print("")
        print("=" * 70)
        print("WARNING: gemma_mode=api — screenshots are sent to Google AI Studio!")
        print("   This disables the local-only privacy guarantee.")
        print("   Set GEMMA_MODE=local to keep all data on your machine.")
        print("=" * 70)
    print()

    # ── Health checks ────────────────────────────────────────────────
    # Auto-start llama-server if not already running
    from engine import model_manager
    if not check_llama_server():
        print("[Main] llama-server not running — starting automatically...")
        llm_server_ok = model_manager.start_server(settings.active_model)
    else:
        llm_server_ok = True
    check_disk_space()
    if not llm_server_ok:
        print()
        print("[Main] WARN - Starting without Gemma 4 -- screenshots will be captured")
        print("[Main]   but NOT analyzed until llama-server is available.")
        print("[Main]   The dashboard and API will still work with existing data.")
        print()
    print()

    # ── Shared services ──────────────────────────────────────────────
    db = Database()
    # Fix any meetings left 'ongoing' from a previous crash
    stale = db.cleanup_stale_meetings()
    if stale:
        print(f"[Database] Cleaned up {stale} stale meeting(s) from previous session")
    # Auto-cleanup old data based on retention setting
    if settings.retention_days > 0:
        cleaned = db.cleanup_old_data(settings.retention_days)
        if cleaned["activities"] > 0 or cleaned["meetings"] > 0:
            print(f"[Database] Retention cleanup: removed {cleaned['activities']} activities, "
                  f"{cleaned['meetings']} meetings older than {settings.retention_days} days")
    embedder = Embedder()

    # Thread-safe shutdown flag (checked by voice transcription thread before DB writes)
    _shutdown = threading.Event()

    # ── Processing queue ─────────────────────────────────────────────
    processing_queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    # ── Workers ──────────────────────────────────────────────────────
    capture_worker = CaptureWorker(queue=processing_queue, database=db)
    analysis_worker = AnalysisWorker(queue=processing_queue, database=db)

    # ── Audio Worker (Meeting Transcription) ─────────────────────────
    audio_worker = AudioWorker(database=db)
    # Inject audio_worker into capture_worker so it can signal meeting detection
    capture_worker._audio_worker = audio_worker

    # ── Hotkey Listener ──────────────────────────────────────────────
    from ui.overlay import show_overlay_notification
    from capture.voice_recorder import VoiceRecorder
    from engine import llm_client

    voice_recorder = VoiceRecorder()

    def _on_bookmark():
        capture_worker.trigger_bookmark()
        show_overlay_notification("📌 Bookmarked", "Screenshot captured and bookmarked", duration=2.5, color="#10b981")

    def _toggle_pause():
        if capture_worker.is_paused:
            capture_worker.resume(source="hotkey")
            print("[Hotkey] >> Capture resumed")
            show_overlay_notification("▶ Capturing Resumed", "Screen recording is active", duration=2.5, color="#8b5cf6")
        else:
            capture_worker.pause(source="hotkey")
            print("[Hotkey] || Capture paused")
            show_overlay_notification("⏸ Capturing Paused", "Screen recording is paused", duration=2.5, color="#f59e0b")

    def _on_voice_start():
        voice_recorder.start()
        show_overlay_notification("🎙️ Recording", "Speak now... release to stop", duration=1.0, color="#ec4899")

    def _on_voice_stop():
        import threading

        result = voice_recorder.stop()
        if result is None:
            show_overlay_notification("⚠️ Too Short", "Recording discarded", duration=1.5, color="#f59e0b")
            return

        wav_bytes, screenshot_path, wav_path = result
        show_overlay_notification("✨ Transcribing...", "Processing voice memo", duration=2.0, color="#8b5cf6")

        # Transcribe in background thread (don't block hotkey handler)
        def _transcribe():
            try:
                transcript = llm_client.transcribe_audio(wav_bytes)
                # Guard: don't write to DB if shutdown is in progress
                if _shutdown.is_set():
                    print("[VoiceMemo] Shutdown in progress — discarding memo")
                    return
                # Save to database as a voice memo activity
                from storage.models import ScreenshotEntry
                from datetime import datetime
                entry = ScreenshotEntry(
                    timestamp=datetime.now(),
                    screenshot_path=str(screenshot_path) if screenshot_path else "",
                    window_title="Voice Memo",
                    detected_app_name="Voice Memo",
                    bookmarked=True,
                    analyzed=False,
                )
                activity_id = db.insert_activity(entry)
                # Update with transcription
                from storage.models import ActivityRecord
                analysis = ActivityRecord(
                    app_name="Voice Memo",
                    activity_category="other",
                    activity_summary=transcript[:200] if transcript else "Voice memo",
                    detailed_context=str(wav_path),
                    mood="neutral",
                    confidence=0.9,
                )
                db.update_activity_analysis(activity_id, analysis)
                print(f"[VoiceMemo] Saved: {transcript[:60]}...")
                show_overlay_notification("✅ Memo Saved", transcript[:50] if transcript else "Saved", duration=2.0, color="#10b981")
            except Exception as e:
                print(f"[VoiceMemo] Transcription failed: {e}")
                show_overlay_notification("❌ Failed", str(e)[:50], duration=2.0, color="#ef4444")

        threading.Thread(target=_transcribe, daemon=True).start()

    hotkey_listener = HotkeyListener(
        bookmark_callback=_on_bookmark,
        pause_callback=_toggle_pause,
        voice_start_callback=_on_voice_start,
        voice_stop_callback=_on_voice_stop,
    )

    # ── API Server ───────────────────────────────────────────────────
    app = create_app(
        database=db,
        embedder=embedder,
        capture_worker=capture_worker,
        analysis_worker=analysis_worker,
        audio_worker=audio_worker,
    )

    # ── Graceful Shutdown ────────────────────────────────────────────
    shutdown_event = asyncio.Event()

    def handle_signal(*_):
        print("\n[Main] Shutdown signal received...")
        _shutdown.set()  # Signal voice transcription thread
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, handle_signal)

    # ── Safety check: warn/block 0.0.0.0 binding without PIN ──────────
    if settings.api_host in ("0.0.0.0", "::"):
        if not settings.dashboard_pin_hash:
            print("")
            print("=" * 70)
            print("WARNING: Binding to 0.0.0.0 exposes ALL screen data to your network!")
            print("   Set a PIN (dashboard_pin_hash) before exposing to the network.")
            print("   Falling back to 127.0.0.1 for safety.")
            print("=" * 70)
            print("")
            settings.api_host = "127.0.0.1"
        else:
            print("[Main] WARNING: Server exposed to network (0.0.0.0). PIN auth is enabled.")

    # ── Start API server in background thread ────────────────────────
    server_config = uvicorn.Config(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level="warning",
    )
    server = uvicorn.Server(server_config)

    # Run uvicorn in a thread so it doesn't block the async loop
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    # ── Start Workers ────────────────────────────────────────────────
    import sys as _sys
    if _sys.platform == "darwin":
        print("[Hotkey] Disabled on macOS (keyboard library lacks support). Use the dashboard.")
    else:
        hotkey_listener.start()

    capture_task = asyncio.create_task(capture_worker.run())
    analysis_task = asyncio.create_task(analysis_worker.run())

    # ── Agent System ─────────────────────────────────────────────────
    agent_scheduler = None
    try:
        from engine.agent_runner import AgentScheduler, get_agents_dir
        import shutil as _shutil
        from pathlib import Path as _Path

        # Copy default agents on first run
        agents_dir = get_agents_dir()
        defaults_dir = _Path(__file__).parent / "default_agents"
        if defaults_dir.exists():
            for f in defaults_dir.iterdir():
                dest = agents_dir / f.name
                if not dest.exists():
                    _shutil.copy2(f, dest)
                    print(f"[Agents] Installed default agent: {f.name}")

        if settings.agents_enabled:
            agent_scheduler = AgentScheduler()
            agent_scheduler.start()
            print(f"[Agents] Scheduler started — scanning {agents_dir}")
    except Exception as e:
        print(f"[Agents] Could not start scheduler: {e}")

    print(f"[Main] Dashboard: http://{settings.api_host}:{settings.api_port}")
    print(f"[Main] API docs:  http://{settings.api_host}:{settings.api_port}/docs")
    print(f"[Main] Bookmark:  {settings.bookmark_hotkey}")
    print()
    print("[Main] ScreenMind is running! Press Ctrl+C to stop.")
    print()

    # ── Wait for shutdown ────────────────────────────────────────────
    await shutdown_event.wait()

    # ── Cleanup ──────────────────────────────────────────────────────
    print("[Main] Shutting down...")
    capture_worker.stop()
    analysis_worker.stop()
    audio_worker.force_stop()
    import sys as _sys
    if _sys.platform != "darwin":
        hotkey_listener.stop()
    if agent_scheduler:
        agent_scheduler.stop()
    server.should_exit = True

    capture_task.cancel()
    analysis_task.cancel()

    try:
        await asyncio.gather(capture_task, analysis_task, return_exceptions=True)
    except asyncio.CancelledError:
        pass

    db.close()
    model_manager.stop_server()
    print("[Main] Goodbye!")


if __name__ == "__main__":
    asyncio.run(main())
