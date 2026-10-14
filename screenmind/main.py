"""
ScreenMind — Main Entry Point
Starts all services: capture, analysis, API server.
Includes startup health checks and graceful error handling.
"""

import logging
import asyncio
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
from pathlib import Path

import uvicorn

from screenmind.config import settings
from screenmind.storage.database import Database
from screenmind.engine.embedder import Embedder
from screenmind.workers.capture_worker import CaptureWorker
from screenmind.workers.analysis_worker import AnalysisWorker
from screenmind.workers.audio_worker import AudioWorker
from screenmind.capture.hotkey import HotkeyListener
from screenmind.api.server import create_app

logger = logging.getLogger("screenmind.main")


def check_llama_server() -> bool:
    """Check if llama-server is reachable and ready for inference."""
    from screenmind.engine import llm_client

    status = llm_client.get_server_status()
    if status["status"] == "ok":
        logger.info(f"OK - llama-server online at {settings.llama_server_host}")
        return True
    elif status["status"] == "unreachable":
        logger.error(f"FAIL - Cannot reach llama-server at {settings.llama_server_host}")
        logger.info(f"Start it with: llama-server -hf ggml-org/gemma-4-E2B-it-GGUF:gemma-4-E2B-it-Q4_0 --mmproj-auto -ngl 99 --port {settings.llama_server_port}")
        return False
    else:
        logger.info(f"WARN - llama-server issue: {status['detail']}")
        return False


def check_disk_space():
    """Warn if disk space is low."""
    try:
        usage = shutil.disk_usage(str(settings.data_path))
        free_gb = usage.free / (1024 ** 3)
        if free_gb < 1.0:
            logger.info(f"WARN - Low disk space: {free_gb:.1f}GB free. ScreenMind needs space for screenshots.")
        else:
            logger.info(f"OK - Disk space: {free_gb:.1f}GB free")
    except Exception:
        pass


def print_first_run_help():
    """Show helpful info on first run (no DB yet)."""
    if not settings.db_path.exists():
        _safe_print()
        _safe_print("  +==========================================+")
        _safe_print("  |  Welcome to ScreenMind -- First Run!     |")
        _safe_print("  +==========================================+")
        _safe_print("  |  Screenshots will be saved to:           |")
        _safe_print(f"  |    {str(settings.screenshots_dir)[:38]:<38} |")
        _safe_print("  |                                          |")
        _safe_print("  |  Press Ctrl+Shift+B to bookmark a moment |")
        _safe_print("  |  Open the dashboard to see your timeline |")
        _safe_print("  +==========================================+")
        _safe_print()
        # Auto-install desktop shortcut on first run
        try:
            _install_desktop_shortcut()
        except Exception:
            pass  # Non-critical — don't block startup



def _is_interactive() -> bool:
    """Check if stdin is attached to a TTY (interactive terminal)."""
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:
        return False


def _is_port_in_use(port: int) -> bool:
    """Check if a port is already bound (another ScreenMind instance?)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _safe_print(*args, **kwargs):
    """Print to stderr, but silently skip if stderr is None (pythonw.exe)."""
    if sys.stderr is not None:
        print(*args, file=sys.stderr, **kwargs)  # noqa: T201


async def main():
    """Initialize and run all ScreenMind services."""

    # ── Single-instance check (before any resource init) ──────────────
    if _is_port_in_use(settings.api_port):
        logger.error(f"Port {settings.api_port} already in use — is ScreenMind already running?")
        logger.error("If not, change api_port in settings or stop the other process.")
        sys.exit(1)

    _safe_print("=" * 60)
    _safe_print("  ScreenMind — Privacy-First Screen Activity Journal")
    _safe_print("  Powered by Gemma 4 E2B (100% Local)")
    _safe_print("=" * 60)
    _safe_print()

    # ── AI dependency check (first-run only) ──────────────────────────
    _missing_ai = []
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        _missing_ai.append("sentence-transformers>=3.3,<4.0")
    try:
        import easyocr  # noqa: F401
    except ImportError:
        _missing_ai.append("easyocr>=1.7.2,<2.0")

    if _missing_ai:
        if _is_interactive():
            _safe_print("=" * 60)
            _safe_print("  ScreenMind requires AI packages for screen analysis.")
            _safe_print("  This is a one-time download of ~2.5 GB (PyTorch + AI models).")
            _safe_print("=" * 60)
            _safe_print()
            answer = input("  Install now? [Y/n]: ").strip().lower()
            if answer in ("", "y", "yes"):
                _safe_print()
                _safe_print("  Installing AI packages (this may take a few minutes)...")
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install"] + _missing_ai,
                    stdout=sys.stderr,
                )
                _safe_print()
                _safe_print("  AI packages installed successfully!")
                _safe_print()
            else:
                _safe_print()
                _safe_print("  ScreenMind requires these packages for screen analysis. Cannot start.")
                _safe_print(f"  Install manually:  pip install {' '.join(_missing_ai)}")
                sys.exit(1)
        else:
            # Non-interactive (background mode, pythonw) — skip, start degraded
            logger.warning("AI packages missing (non-interactive mode). Install with: pip install screenmind[ai]")
            logger.warning("Starting without AI features (capture-only).")

    # ── First-run experience ─────────────────────────────────────────
    settings.ensure_dirs()
    print_first_run_help()

    logger.info(f"Data directory: {settings.data_path}")
    logger.info(f"Capture interval: {settings.capture_interval}s")
    logger.info(f"Model: {settings.active_model} ({settings.gemma_mode} mode)")
    if settings.blocked_apps_list:
        logger.info(f"Privacy zones: {', '.join(settings.blocked_apps_list)}")
    if settings.gemma_mode == "api":
        _safe_print("")
        _safe_print("=" * 70)
        _safe_print("WARNING: gemma_mode=api — screenshots are sent to Google AI Studio!")
        _safe_print("   This disables the local-only privacy guarantee.")
        _safe_print("   Set GEMMA_MODE=local to keep all data on your machine.")
        _safe_print("=" * 70)
    _safe_print()

    # ── llama-server setup ─────────────────────────────────────────────
    # Check if llama-server binary is available; offer to install if missing
    from screenmind.setup_llama import ensure_llama_server
    llama_binary_available = ensure_llama_server()

    # ── Health checks ────────────────────────────────────────────────
    from screenmind.engine import model_manager
    if llama_binary_available:
        # Binary exists — check if server is running, start if not
        if not check_llama_server():
            logger.info("llama-server not running — starting automatically...")
            llm_server_ok = model_manager.start_server(settings.active_model, timeout=120)
        else:
            llm_server_ok = True
            # Detect what model the external server has loaded
            detection = model_manager.detect_running_model()
            if detection:
                model_manager.adopt_external_server(detection)
    else:
        llm_server_ok = False

    check_disk_space()
    if not llm_server_ok:
        _safe_print()
        logger.warning("Starting without Gemma 4 -- screenshots will be captured")
        logger.warning("but NOT analyzed until llama-server is available.")
        logger.warning("The dashboard and API will still work with existing data.")
        if not llama_binary_available:
            logger.info("Run 'python -m screenmind.setup_llama' to install llama-server.")
        _safe_print()
    _safe_print()

    # ── Shared services ──────────────────────────────────────────────
    db = Database()
    # Fix any meetings left 'ongoing' from a previous crash
    stale = db.cleanup_stale_meetings()
    if stale:
        logger.info(f"Cleaned up {stale} stale meeting(s) from previous session")
    # Auto-cleanup old data based on retention setting
    if settings.retention_days > 0:
        cleaned = db.cleanup_old_data(settings.retention_days)
        if cleaned["activities"] > 0 or cleaned["meetings"] > 0:
            logger.info(f"Retention cleanup: removed {cleaned['activities']} activities, "
                  f"{cleaned['meetings']} meetings older than {settings.retention_days} days")
    embedder = Embedder()

    # Thread-safe shutdown flag (checked by voice transcription thread before DB writes)
    _shutdown = threading.Event()

    # ── Processing queue ─────────────────────────────────────────────
    processing_queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    # ── Workers ──────────────────────────────────────────────────────
    capture_worker = CaptureWorker(queue=processing_queue, database=db)
    analysis_worker = AnalysisWorker(queue=processing_queue, database=db)

    # ── Restore persisted capture state ──────────────────────────────
    if not settings.capture_paused:
        capture_worker.resume(source="startup_restore")
        logger.info("Capture auto-resumed from previous session.")

    # ── Audio Worker (Meeting Transcription) ─────────────────────────
    audio_worker = AudioWorker(database=db)
    # Inject audio_worker into capture_worker so it can signal meeting detection
    capture_worker._audio_worker = audio_worker

    # ── Hotkey Listener ──────────────────────────────────────────────
    from screenmind.ui.overlay import show_overlay_notification
    from screenmind.capture.voice_recorder import VoiceRecorder

    voice_recorder = VoiceRecorder()

    def _on_bookmark():
        if capture_worker.trigger_bookmark():
            show_overlay_notification("📌 Bookmarked", "Screenshot captured and bookmarked", duration=2.5, color="#10b981")
        else:
            show_overlay_notification("🕶️ Incognito", "Nothing is captured while incognito is on", duration=2.5, color="#f59e0b")

    def _toggle_pause():
        if capture_worker.is_paused:
            capture_worker.resume(source="hotkey")
            show_overlay_notification("▶ Capturing Resumed", "Screen recording is active", duration=2.5, color="#8b5cf6")
        else:
            capture_worker.pause(source="hotkey")
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
            from screenmind.engine.voice_memo import save_voice_memo
            try:
                # Always saved — even without a transcript the audio and
                # screenshot stay available for playback
                result = save_voice_memo(
                    db, wav_bytes, screenshot_path, wav_path,
                    is_cancelled=_shutdown.is_set,
                )
            except Exception as e:
                logger.error(f"Failed to save voice memo: {e}")
                show_overlay_notification("❌ Memo Not Saved", "Could not save voice memo", duration=2.5, color="#ef4444")
                return
            if result is None:
                return  # Shutdown in progress
            if result["status"] == "ok":
                show_overlay_notification("✅ Memo Saved", result["transcript"][:50], duration=2.0, color="#10b981")
            elif result["status"] == "empty":
                show_overlay_notification("✅ Memo Saved", "Audio saved — transcription unavailable", duration=2.5, color="#f59e0b")
            else:
                show_overlay_notification("❌ Transcription Failed", "Audio saved — transcription failed", duration=2.5, color="#ef4444")

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
        _safe_print("\n[Main] Shutdown signal received...")
        _shutdown.set()  # Signal voice transcription thread
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, handle_signal)

    # ── Safety check: warn/block 0.0.0.0 binding without PIN ──────────
    if settings.api_host in ("0.0.0.0", "::"):
        if not settings.dashboard_pin_hash:
            _safe_print("")
            _safe_print("=" * 70)
            _safe_print("WARNING: Binding to 0.0.0.0 exposes ALL screen data to your network!")
            _safe_print("   Set a PIN (dashboard_pin_hash) before exposing to the network.")
            _safe_print("   Falling back to 127.0.0.1 for safety.")
            _safe_print("=" * 70)
            _safe_print("")
            settings.api_host = "127.0.0.1"
        else:
            logger.warning("WARNING: Server exposed to network (0.0.0.0). PIN auth is enabled.")

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
    hotkey_listener.start()

    capture_task = asyncio.create_task(capture_worker.run())
    analysis_task = asyncio.create_task(analysis_worker.run())

    # ── Agent System ─────────────────────────────────────────────────
    agent_scheduler = None
    try:
        from screenmind.engine.agent_runner import AgentScheduler, get_agents_dir
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
                    logger.info(f"Installed default agent: {f.name}")

        if settings.agents_enabled:
            agent_scheduler = AgentScheduler()
            agent_scheduler.start()
            logger.info(f"Scheduler started — scanning {agents_dir}")
    except Exception as e:
        logger.info(f"Could not start scheduler: {e}")

    logger.info(f"Dashboard: http://{settings.api_host}:{settings.api_port}")
    logger.info(f"API docs:  http://{settings.api_host}:{settings.api_port}/docs")
    logger.info(f"Bookmark:  {settings.bookmark_hotkey}")
    _safe_print()
    logger.info("ScreenMind is running! Press Ctrl+C to stop.")
    _safe_print()

    # ── Wait for shutdown ────────────────────────────────────────────
    await shutdown_event.wait()

    # ── Cleanup ──────────────────────────────────────────────────────
    logger.info("Shutting down...")
    capture_worker.stop()
    analysis_worker.stop()
    audio_worker.force_stop()
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
    logger.info("Goodbye!")


def _install_desktop_shortcut() -> None:
    """Create a desktop shortcut for ScreenMind (cross-platform)."""
    desktop = Path.home() / "Desktop"
    if not desktop.exists():
        desktop = Path.home()

    launcher_py = Path(__file__).parent / "launcher.py"
    data_dir = settings.data_path
    data_dir.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        # Create VBS wrapper in data dir (not package dir — avoids PermissionError)
        vbs_path = data_dir / "launcher.vbs"
        python_exe = sys.executable
        vbs_path.write_text(
            f'Set WshShell = CreateObject("WScript.Shell")\n'
            f'WshShell.Run """{python_exe}"" ""{launcher_py}""", 0, False\n',
            encoding="utf-8",
        )

        # Create .lnk shortcut
        try:
            shortcut_path = desktop / "ScreenMind.lnk"
            ps_cmd = (
                f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{shortcut_path}");'
                f'$s.TargetPath="wscript.exe";'
                f'$s.Arguments="`"{vbs_path}`"";'
                f'$s.WorkingDirectory="{launcher_py.parent.parent}";'
                f'$s.Description="ScreenMind - Privacy-First AI Screen Journal";'
            )
            icon_path = Path(__file__).parent / "assets" / "favicon.ico"
            if icon_path.exists():
                ps_cmd += f'$s.IconLocation="{icon_path}";'
            ps_cmd += '$s.Save()'
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True,
            )
            print(f"[OK] Desktop shortcut created: {shortcut_path}")  # noqa: T201
        except Exception as e:
            print(f"[FAIL] Failed to create shortcut: {e}")  # noqa: T201

    elif sys.platform == "darwin":
        cmd_path = desktop / "ScreenMind.command"
        cmd_path.write_text(
            f'#!/bin/bash\n"{sys.executable}" "{launcher_py}"\n',
            encoding="utf-8",
        )
        os.chmod(str(cmd_path), 0o755)
        print(f"[OK] Desktop launcher created: {cmd_path}")  # noqa: T201

    else:
        desktop_file = desktop / "screenmind.desktop"
        desktop_file.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=ScreenMind\n"
            "Comment=Privacy-First AI Screen Journal\n"
            f'Exec="{sys.executable}" "{launcher_py}"\n'
            "Terminal=false\n"
            "Categories=Utility;\n",
            encoding="utf-8",
        )
        os.chmod(str(desktop_file), 0o755)
        print(f"[OK] Desktop launcher created: {desktop_file}")  # noqa: T201


def run():
    """Sync entry point for CLI: `screenmind` command."""
    # ── Exit-early flags (checked in order to prevent --background from swallowing them) ──
    if "--version" in sys.argv:
        from screenmind import __version__
        print(f"screenmind {__version__}")  # noqa: T201
        return
    if "--help" in sys.argv or "-h" in sys.argv:
        from screenmind import __version__
        print(f"ScreenMind {__version__} -- Privacy-First AI Screen Activity Journal")  # noqa: T201
        print()  # noqa: T201
        print("Usage: screenmind [OPTIONS]")  # noqa: T201
        print()  # noqa: T201
        print("Options:")  # noqa: T201
        print("  --version            Show version and exit")  # noqa: T201
        print("  --help, -h           Show this help and exit")  # noqa: T201
        print("  --background         Run silently without a console window")  # noqa: T201
        print("  --launch             Start with splash screen + open dashboard")  # noqa: T201
        print("  --install-startup    Register ScreenMind to start at system login")  # noqa: T201
        print("  --uninstall-startup  Remove ScreenMind from system startup")  # noqa: T201
        print("  --install-shortcut   Create a desktop shortcut")  # noqa: T201
        return

    # ── Startup registration (before --background to prevent swallowing) ──
    if "--install-startup" in sys.argv:
        from screenmind.startup import install_startup
        ok = install_startup()
        sys.exit(0 if ok else 1)
    if "--uninstall-startup" in sys.argv:
        from screenmind.startup import uninstall_startup
        ok = uninstall_startup()
        sys.exit(0 if ok else 1)

    # ── Desktop shortcut ──────────────────────────────────────────────
    if "--install-shortcut" in sys.argv:
        _install_desktop_shortcut()
        return
    if "--launch" in sys.argv:
        from screenmind.launcher import main as launch_main
        launch_main()
        return

    # ── Background mode: re-launch headless and exit ──
    if "--background" in sys.argv:
        log_path = settings.data_path / "screenmind.log"
        settings.data_path.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["SCREENMIND_LOG_FILE"] = str(log_path)

        if sys.platform == "win32":
            # Try pythonw (no console window)
            pythonw = sys.executable.replace("python.exe", "pythonw.exe")
            if Path(pythonw).exists():
                subprocess.Popen(
                    [pythonw, "-m", "screenmind"],
                    stdin=subprocess.DEVNULL,
                    env=env,
                )
            else:
                # Fallback: CREATE_NO_WINDOW with regular python
                subprocess.Popen(
                    [sys.executable, "-m", "screenmind"],
                    stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                    env=env,
                )
        else:
            # macOS/Linux: detach from terminal
            subprocess.Popen(
                [sys.executable, "-m", "screenmind"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )

        print(f"ScreenMind started in background. Logs: {log_path}")  # noqa: T201
        print(f"Dashboard: http://{settings.api_host}:{settings.api_port}")  # noqa: T201
        return

    asyncio.run(main())


if __name__ == "__main__":
    run()
