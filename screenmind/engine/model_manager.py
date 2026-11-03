"""
Model Manager for ScreenMind
Handles llama-server process lifecycle, GGUF model downloads, and model switching.
"""

import logging
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from screenmind.config import settings

logger = logging.getLogger("screenmind.engine.model_manager")


# Available models with HuggingFace download info
AVAILABLE_MODELS = [
    {
        "key": "gemma-4-e2b",
        "name": "Gemma 4 E2B",
        "size": "2B",
        "vram": "~4 GB",
        "quality": "Good",
        "tier": 1,
        "hf_repo": "ggml-org/gemma-4-E2B-it-GGUF",
        "hf_file": "gemma-4-E2B-it-Q4_0.gguf",
        "mmproj_file": "mmproj-gemma-4-E2B-it-Q8_0.gguf",
        "audio": True,
        "vision": True,
        "variants": [
            {"quant": "Q4_0", "hf_file": "gemma-4-E2B-it-Q4_0.gguf", "file_size": "~1.5 GB", "label": "Q4_0 — Smallest, fastest"},
            {"quant": "Q8_0", "hf_file": "gemma-4-E2B-it-Q8_0.gguf", "file_size": "~2.7 GB", "label": "Q8_0 — Better quality"},
            {"quant": "BF16", "hf_file": "gemma-4-E2B-it-BF16.gguf", "file_size": "~5.2 GB", "label": "BF16 — Full precision"},
        ],
    },
    {
        "key": "gemma-4-e4b",
        "name": "Gemma 4 E4B",
        "size": "4B",
        "vram": "~6 GB",
        "quality": "Great",
        "tier": 2,
        "hf_repo": "ggml-org/gemma-4-E4B-it-GGUF",
        "hf_file": "gemma-4-E4B-it-Q4_0.gguf",
        "mmproj_file": "mmproj-gemma-4-E4B-it-Q8_0.gguf",
        "audio": True,
        "vision": True,
        "variants": [
            {"quant": "Q4_0", "hf_file": "gemma-4-E4B-it-Q4_0.gguf", "file_size": "~2.5 GB", "label": "Q4_0 — Smallest, fastest"},
            {"quant": "Q8_0", "hf_file": "gemma-4-E4B-it-Q8_0.gguf", "file_size": "~4.6 GB", "label": "Q8_0 — Better quality"},
            {"quant": "BF16", "hf_file": "gemma-4-E4B-it-BF16.gguf", "file_size": "~9.0 GB", "label": "BF16 — Full precision"},
        ],
    },
    {
        "key": "gemma-4-12b",
        "name": "Gemma 4 12B",
        "size": "12B",
        "vram": "~10 GB",
        "quality": "Excellent",
        "tier": 3,
        "hf_repo": "bartowski/gemma-4-12B-it-GGUF",
        "hf_file": "gemma-4-12B-it-Q4_K_M.gguf",
        "mmproj_file": "mmproj-gemma-4-12B-it-bf16.gguf",
        "audio": True,
        "vision": True,
        "variants": [
            {"quant": "IQ3_M",  "hf_file": "gemma-4-12B-it-IQ3_M.gguf",  "file_size": "~5.5 GB", "label": "IQ3_M — Smallest, lower quality"},
            {"quant": "Q4_K_M", "hf_file": "gemma-4-12B-it-Q4_K_M.gguf", "file_size": "~7.5 GB", "label": "Q4_K_M — Balanced (default)"},
            {"quant": "Q5_K_M", "hf_file": "gemma-4-12B-it-Q5_K_M.gguf", "file_size": "~8.7 GB", "label": "Q5_K_M — Better quality"},
            {"quant": "Q6_K",   "hf_file": "gemma-4-12B-it-Q6_K.gguf",   "file_size": "~10 GB",  "label": "Q6_K — High quality"},
            {"quant": "Q8_0",   "hf_file": "gemma-4-12B-it-Q8_0.gguf",   "file_size": "~13 GB",  "label": "Q8_0 — Near-lossless"},
        ],
    },
]


# Server process state
_server_process: Optional[subprocess.Popen] = None
_server_lock = threading.Lock()
_active_model_key: Optional[str] = None

# External server state — set when we detect a server we didn't spawn
_external_server: bool = False
_external_loading: bool = False  # external server answers /health with 503
_external_model_name: Optional[str] = None  # model ID for non-listed models
EXTERNAL_PROBE_INTERVAL = 10.0  # seconds between background external server probes

# Download state — single-flight + thread-safe reads/writes
_download_lock = threading.Lock()      # guards the entire download→start lifecycle
_download_state_lock = threading.Lock()  # guards state dict + cancel flag reads/writes
_cancel_download_flag = False  # cancel signal for active download (guarded by _download_state_lock)
_download_state: dict = {
    "active": False,
    "model": None,
    "status": "idle",           # idle | downloading | starting | done | error
    "downloaded_bytes": 0,
    "message": "",
}


def _set_download_state(**kwargs) -> None:
    """Thread-safe update of download state."""
    global _download_state
    with _download_state_lock:
        _download_state = {**_download_state, **kwargs}


def get_download_state() -> dict:
    """Get a copy of the current download state (safe from any thread)."""
    with _download_state_lock:
        return dict(_download_state)


def _clear_error_state() -> None:
    """Clear a sticky error state (called when a new download or retry starts)."""
    st = get_download_state()
    if st["status"] == "error" and not st["active"]:
        _set_download_state(status="idle", message="")



def cancel_download() -> bool:
    """
    Request cancellation of an active download.
    The download thread checks this flag every ~2s and kills the subprocess.
    Returns True if a download was active and cancel was requested.
    """
    global _cancel_download_flag
    with _download_state_lock:
        dl = dict(_download_state)
        if dl["active"] and dl["status"] == "downloading":
            _cancel_download_flag = True
            logger.info("Cancel requested")
            return True
    return False


# ── External server detection ──────────────────────────────────────────
# An llama-server we didn't spawn — started by hand, by another tool, or on
# another machine — is found at LLAMA_SERVER_HOST (the URL llm_client sends
# requests to), not at 127.0.0.1:LLAMA_SERVER_PORT, which is only where we
# spawn our own.

def _server_url() -> str:
    return settings.llama_server_host.rstrip("/")


def _probe_health() -> str:
    """Probe LLAMA_SERVER_HOST/health: "ok", "loading" (503 while llama-server
    loads a model) or "down" (unreachable, or not an llama-server)."""
    try:
        import httpx
        r = httpx.get(f"{_server_url()}/health", timeout=2)
    except Exception:
        return "down"
    if r.status_code == 200:
        return "ok"
    if r.status_code == 503:
        return "loading"
    return "down"


def detect_running_model() -> Optional[dict]:
    """
    Probe a running llama-server's /v1/models to identify the loaded model.
    Returns:
      {"matched": True, "key": str, "quant": str, "name": str}  — known model
      {"matched": False, "name": str}                            — unknown model
      None                                                       — probe failed
    """
    try:
        import httpx
        r = httpx.get(f"{_server_url()}/v1/models", timeout=3)
        if r.status_code != 200:
            return None
        data = r.json()
        model_list = data.get("data", [])
        if not model_list:
            return None
        model_id = model_list[0].get("id", "")
        if not model_id:
            return None

        # Match against known variants by hf_file substring
        for m in AVAILABLE_MODELS:
            for v in m.get("variants", []):
                if v["hf_file"] in model_id:
                    return {"matched": True, "key": m["key"], "quant": v["quant"], "name": m["name"]}
        # No match — unknown model
        # Clean up the model_id for display (strip path, keep filename)
        display_name = model_id.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        return {"matched": False, "name": display_name}
    except Exception as e:
        logger.debug(f"External model detection failed: {e}")
        return None


def adopt_external_server(detection: dict) -> None:
    """
    Record that an externally-started server is active (and ready).
    Called by sync_external_server() on every probe, so it only logs when the
    adopted model changes.
    """
    global _active_model_key, _external_server, _external_model_name, _external_loading
    if detection.get("matched"):
        key, name = detection["key"], None
    else:
        key, name = None, detection.get("name", "Unknown model")
    changed = not _external_server or (key, name) != (_active_model_key, _external_model_name)
    _external_server = True
    _external_loading = False
    _active_model_key = key
    _external_model_name = name
    if changed:
        if key:
            logger.info(f"Adopted external server: {detection['name']} ({detection.get('quant', '?')})")
        else:
            logger.info(f"Adopted external server: {name} (not in model list)")


def _drop_external_server() -> None:
    """Forget the external server (it went away)."""
    global _active_model_key, _external_server, _external_model_name, _external_loading
    if _external_server:
        logger.info("External llama-server is no longer reachable")
        _active_model_key = None
    _external_server = False
    _external_loading = False
    _external_model_name = None


def is_external_server() -> bool:
    """True when the llama-server in use was started outside ScreenMind."""
    return _external_server


def sync_external_server() -> bool:
    """
    Detect, adopt, refresh or drop an llama-server we didn't spawn.

    Probes LLAMA_SERVER_HOST. Called at startup, by the background watcher
    every EXTERNAL_PROBE_INTERVAL seconds, and before a switch/restart.
    Skipped while we own a server process or a download/switch/restart is in
    progress. A server still loading its model (503) is kept as
    external-but-loading so we never spawn a second server onto its port.
    Returns whether an external server is in use.
    """
    global _external_server, _external_loading
    # Never block on start_server(): it holds the lock while our server boots
    if not _server_lock.acquire(blocking=False):
        return _external_server
    try:
        if _owns_server() or get_download_state()["active"]:
            return _external_server
        health = _probe_health()
        if health == "ok":
            adopt_external_server(
                detect_running_model() or {"matched": False, "name": "Unknown model"}
            )
            _clear_error_state()  # e.g. a Retry that lost the port to this server
        elif health == "loading":
            if not _external_server:
                logger.info("External llama-server found, still loading its model")
            _external_server = True
            _external_loading = True
        else:
            _drop_external_server()
        return _external_server
    finally:
        _server_lock.release()


def start_external_watcher() -> threading.Thread:
    """Re-check for an external server in the background, so one started,
    restarted or swapped after ScreenMind starts is picked up without a
    restart — and status polls never wait on the network."""
    def _loop():
        while True:
            time.sleep(EXTERNAL_PROBE_INTERVAL)
            try:
                sync_external_server()
            except Exception as e:
                logger.debug(f"External server check failed: {e}")

    t = threading.Thread(target=_loop, name="external-llama-watcher", daemon=True)
    t.start()
    return t


# ── Model directory + variant helpers ──────────────────────────────────


def _models_dir() -> Path:
    """Returns ~/.screenmind/models/ — cross-platform, auto-created."""
    d = Path.home() / ".screenmind" / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_model_info(key: str) -> Optional[dict]:
    """Get model metadata by key."""
    for m in AVAILABLE_MODELS:
        if m["key"] == key:
            return m
    return None


def get_effective_hf_file(key: str) -> str:
    """Resolves user's variant choice → hf_file. Never mutates AVAILABLE_MODELS."""
    info = get_model_info(key)
    if not info:
        return ""
    quant = settings.model_variants.get(key)
    if quant:
        for v in info.get("variants", []):
            if v["quant"] == quant:
                return v["hf_file"]
    return info["hf_file"]  # default


def get_active_quant(key: str) -> str:
    """Returns the quant string for user's selected variant (or default)."""
    info = get_model_info(key)
    if not info:
        return ""
    quant = settings.model_variants.get(key)
    if quant and any(v["quant"] == quant for v in info.get("variants", [])):
        return quant
    # Default = first variant's quant
    return info["variants"][0]["quant"] if info.get("variants") else ""


def _quant_for_hf_file(key: str, hf_file: str) -> str:
    """Reverse-map an hf_file → quant name (for path building)."""
    info = get_model_info(key)
    if not info:
        return ""
    for v in info.get("variants", []):
        if v["hf_file"] == hf_file:
            return v["quant"]
    return ""


def is_audio_capable(key: Optional[str] = None) -> bool:
    """Check if the given (or active) model supports audio input."""
    k = key or get_active_model() or settings.active_model
    info = get_model_info(k)
    return info.get("audio", False) if info else False


def get_active_capabilities() -> dict:
    """Get capability flags for the active model.

    For an external server running a model we don't recognise, both are
    None (unknown) — not the configured model's capabilities.
    """
    if _external_server and _external_model_name and not _owns_server():
        return {"audio": None, "vision": None}
    k = get_active_model() or settings.active_model
    info = get_model_info(k)
    if not info:
        return {"audio": False, "vision": False}
    return {"audio": info.get("audio", False), "vision": info.get("vision", False)}


# ── Variant-aware download detection ──────────────────────────────────

def is_variant_downloaded(key: str, quant: str) -> bool:
    """Check if a specific variant is downloaded in ~/.screenmind/models/."""
    info = get_model_info(key)
    if not info:
        return False
    variant = next((v for v in info.get("variants", []) if v["quant"] == quant), None)
    if not variant:
        return False
    model_file = _models_dir() / key / quant / variant["hf_file"]
    return model_file.exists() and model_file.stat().st_size > 1024 * 1024


def is_model_downloaded(key: str) -> bool:
    """Check if ANY variant of a model is downloaded (backward compat)."""
    info = get_model_info(key)
    if not info:
        return False
    return any(is_variant_downloaded(key, v["quant"]) for v in info.get("variants", []))


def list_models() -> list:
    """List all available models with per-variant download status."""
    global _active_model_key
    result = []
    for m in AVAILABLE_MODELS:
        active_quant = get_active_quant(m["key"])
        variants_with_status = [
            {**v, "downloaded": is_variant_downloaded(m["key"], v["quant"])}
            for v in m.get("variants", [])
        ]
        status = "not_installed"
        if m["key"] == _active_model_key and is_server_running():
            status = "active"
        elif is_model_downloaded(m["key"]):
            status = "downloaded"
        result.append({
            **m, "status": status,
            "active_variant": active_quant,
            "variants": variants_with_status,
        })
    return result



def _do_download(key: str, hf_file: str, quant: str) -> bool:
    """
    Internal: download a model GGUF + mmproj from HuggingFace.
    Caller must hold _download_lock. Updates _download_state as it progresses.
    Supports cancellation via _cancel_download_flag.

    hf_file and quant are locked-in at call time — never re-resolved from config.
    """
    global _cancel_download_flag
    info = get_model_info(key)
    if not info:
        return False

    variant_dir = _models_dir() / key / quant

    with _download_state_lock:
        _cancel_download_flag = False
    _set_download_state(
        active=True, model=key, status="downloading",
        downloaded_bytes=0, message=f"Downloading {info['name']} ({quant})...",
    )

    logger.info(f"Downloading {info['name']} ({quant}) from {info['hf_repo']}...")

    try:
        # Use sys.argv for paths — avoids injection if username has quotes
        cmd = [
            sys.executable, "-c",
            "import sys; from huggingface_hub import hf_hub_download; "
            "hf_hub_download(repo_id=sys.argv[1], filename=sys.argv[2], local_dir=sys.argv[3])",
            info["hf_repo"], hf_file, str(variant_dir),
        ]

        # Redirect stdout to DEVNULL (progress is polled from dir size).
        # Capture stderr to a temp file so we keep error messages without
        # risking a PIPE deadlock — HF writes progress bars to stderr
        # continuously, which can fill the 64KB OS pipe buffer and hang.
        err_file = tempfile.TemporaryFile()
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,   # prevent hangs from HF auth prompts
            stdout=subprocess.DEVNULL,
            stderr=err_file,
        )

        while proc.poll() is None:
            # Check cancel flag (under lock for consistency)
            with _download_state_lock:
                should_cancel = _cancel_download_flag
            if should_cancel:
                logger.info(f"Download cancelled: {info['name']}")
                try:
                    proc.kill()
                    proc.wait(timeout=10)
                except Exception:
                    pass  # Already dead — fine
                err_file.close()
                # Brief sleep for Windows handle release before cleanup
                time.sleep(0.5)
                # Clean up partial variant dir
                if variant_dir.exists():
                    try:
                        shutil.rmtree(variant_dir)
                    except Exception as e:
                        logger.debug(f"Cleanup error: {e}")
                _set_download_state(
                    active=False, status="idle", model="",
                    downloaded_bytes=0, message="Download cancelled",
                )
                with _download_state_lock:
                    _cancel_download_flag = False
                return False

            time.sleep(2)  # 2s check interval (faster cancel response)
            # Poll progress from variant dir + .huggingface temp dir
            total_bytes = 0
            try:
                for scan_dir in [variant_dir, variant_dir / ".huggingface"]:
                    if scan_dir.exists():
                        for f in scan_dir.rglob("*"):
                            if f.is_file():
                                try:
                                    total_bytes += f.stat().st_size
                                except OSError:
                                    pass
            except Exception:
                pass
            # Monotonic: never go backwards
            cur = get_download_state().get("downloaded_bytes", 0)
            _set_download_state(downloaded_bytes=max(cur, total_bytes),
                                message=f"Downloading {info['name']} ({quant})...")

        if proc.returncode != 0:
            err_file.seek(0)
            stderr = err_file.read().decode(errors="replace")[:200]
            err_file.close()
            logger.error(f"Download failed: {stderr}")
            _set_download_state(status="error", message=f"Download failed: {stderr[:100]}")
            return False
        err_file.close()
        logger.info(f"Model download complete: {info['name']} ({quant})")

        # Download mmproj if not already present (shared per model)
        mmproj_dir = _models_dir() / key
        mmproj_path = mmproj_dir / info["mmproj_file"]
        if not mmproj_path.exists():
            logger.info(f"Downloading mmproj: {info['mmproj_file']}...")
            _set_download_state(message=f"Downloading vision projector...")
            cmd_mmproj = [
                sys.executable, "-c",
                "import sys; from huggingface_hub import hf_hub_download; "
                "hf_hub_download(repo_id=sys.argv[1], filename=sys.argv[2], local_dir=sys.argv[3])",
                info["hf_repo"], info["mmproj_file"], str(mmproj_dir),
            ]
            mmproj_proc = subprocess.Popen(
                cmd_mmproj,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            mmproj_proc.wait(timeout=600)  # 10 min max for mmproj
            if mmproj_proc.returncode != 0:
                logger.error("mmproj download failed")
                _set_download_state(status="error", message="Vision projector download failed")
                return False
            logger.info("mmproj download complete")

        return True
    except Exception as e:
        logger.error(f"Download error: {e}")
        _set_download_state(status="error", message=f"Error: {str(e)[:100]}")
        try:
            err_file.close()
        except Exception:
            pass
        return False


def start_server(model_key: Optional[str] = None, timeout: int = 60, hf_file: str = None) -> bool:
    """
    Start llama-server with the specified model.
    If already running with the same model, does nothing.
    If running with a different model, restarts.

    Args:
        timeout: seconds to wait for /health (60 normal, 180 for cold start after download)
        hf_file: if provided, use this file directly (avoids re-resolving from config)
    """
    global _server_process, _active_model_key

    key = model_key or settings.active_model
    info = get_model_info(key)
    if not info:
        logger.warning(f"Unknown model: {key}")
        return False

    with _server_lock:
        # Clear external server state — we're taking over. Callers check
        # is_external_server() first; spawning onto an external server's
        # port would fail.
        global _external_server, _external_model_name, _external_loading
        _external_server = False
        _external_loading = False
        _external_model_name = None

        # Already running with this model?
        if _server_process and _server_process.poll() is None and _active_model_key == key:
            return True

        # Stop existing server (inline — we already hold the lock)
        if _server_process:
            try:
                _server_process.terminate()
                _server_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _server_process.kill()
            except Exception:
                pass
            _server_process = None
            _active_model_key = None

        # Resolve variant paths
        if not hf_file:
            hf_file = get_effective_hf_file(key)
        quant = _quant_for_hf_file(key, hf_file)
        if not quant:
            logger.error(f"Cannot resolve quant for {hf_file}")
            return False

        model_path = _models_dir() / key / quant / hf_file
        mmproj_path = _models_dir() / key / info["mmproj_file"]

        # Pre-flight check — fail fast instead of waiting for timeout
        if not model_path.exists():
            logger.error(f"Model file not found: {model_path}")
            return False
        if not mmproj_path.exists():
            logger.error(f"mmproj not found: {mmproj_path}")
            return False

        port = settings.llama_server_port

        # Find llama-server binary: check project's llama/ folder first, then PATH
        bin_name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
        llama_bin = bin_name

        # Detect dev vs pip install for llama binary location
        import sysconfig
        _site_packages = Path(sysconfig.get_path("purelib"))
        _pkg_dir = Path(__file__).parent.parent  # screenmind/
        if _pkg_dir.is_relative_to(_site_packages):
            project_bin = Path.home() / ".screenmind" / "llama" / bin_name
        else:
            project_bin = _pkg_dir.parent / "llama" / bin_name

        if project_bin.exists():
            llama_bin = str(project_bin)

        cmd = [
            llama_bin,
            "-m", str(model_path),
            "--mmproj", str(mmproj_path),
            "--port", str(port),
            "-ngl", str(settings.num_gpu_layers),
            "-c", str(settings.context_window),
            "--parallel", "1",   # Single slot — analysis/audio/chat are sequential
            "--no-warmup",
        ]

        # Flash attention — faster + less VRAM, but not all GPUs support it
        if settings.flash_attention:
            cmd.extend(["--flash-attn", "on"])

        # KV cache quantization — saves ~60% KV VRAM with negligible quality loss
        if settings.kv_cache_quant:
            cmd.extend(["--cache-type-k", "q8_0", "--cache-type-v", "q4_0"])

        logger.info(f"Starting llama-server: {info['name']} on port {port} (timeout={timeout}s)")

        try:
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0

            # Use DEVNULL for stdout/stderr to prevent pipe buffer deadlock.
            # llama-server writes a lot of logs — if we use PIPE and never read,
            # the OS buffer fills and the process hangs.
            _server_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                startupinfo=startupinfo,
            )

            # Wait for server to be ready (poll /health)
            for i in range(timeout):
                time.sleep(1)
                if _server_process.poll() is not None:
                    logger.warning(f"Server exited early (code: {_server_process.returncode})")
                    _server_process = None
                    return False
                try:
                    import httpx
                    r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2)
                    if r.status_code == 200:
                        _active_model_key = key
                        logger.info(f"Server ready ({i+1}s)")
                        return True
                except Exception:
                    pass

            logger.warning(f"Server failed to start within {timeout}s")
            stop_server()
            return False

        except FileNotFoundError:
            logger.error("llama-server not found.")
            if sys.platform == "win32":
                logger.error("  Run: python -m screenmind.setup_llama")
                logger.error("  Or download from: https://github.com/ggml-org/llama.cpp/releases")
            elif sys.platform == "darwin":
                logger.error("  Run: brew install llama.cpp")
                logger.error("  Or:  python -m screenmind.setup_llama")
            else:
                logger.error("  Run: python -m screenmind.setup_llama")
                logger.error("  Or download from: https://github.com/ggml-org/llama.cpp/releases")
            return False
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            return False


def stop_server():
    """Stop the running llama-server process."""
    global _server_process, _active_model_key

    with _server_lock:
        if _server_process:
            try:
                _server_process.terminate()
                _server_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _server_process.kill()
            except Exception:
                pass
            _server_process = None
            _active_model_key = None
            logger.info("Server stopped")


def switch_model(key: str) -> bool:
    """
    Switch to a different model (restarts server).
    Verifies the selected variant exists; falls back to any downloaded variant.
    Respects _download_lock: refuses if a download lifecycle is active,
    and prevents concurrent switches from racing each other.
    Sets transient 'starting' state so UI shows "Booting up..." instead of "error".
    """
    info = get_model_info(key)
    if not info:
        return False
    if _external_server:
        logger.warning("Cannot switch models — llama-server is managed externally")
        return False
    if not is_model_downloaded(key):
        logger.warning(f"Cannot switch to {key} — not downloaded")
        return False

    # Resolve which variant to use — fall back if selected variant is missing
    quant = get_active_quant(key)
    hf_file = get_effective_hf_file(key)
    if not is_variant_downloaded(key, quant):
        # Fall back to any downloaded variant
        for v in info.get("variants", []):
            if is_variant_downloaded(key, v["quant"]):
                quant = v["quant"]
                hf_file = v["hf_file"]
                # Update saved preference to this fallback
                variants = dict(settings.model_variants)
                variants[key] = quant
                settings.save_runtime_overrides({"model_variants": variants})
                logger.info(f"Fell back to variant {quant} for {key}")
                break
        else:
            logger.warning(f"Cannot switch to {key} — no variant downloaded")
            return False

    if not _download_lock.acquire(blocking=False):
        logger.warning("Lifecycle in progress, switch ignored")
        return False
    try:
        _clear_error_state()
        _set_download_state(
            active=True, model=key, status="starting",
            downloaded_bytes=0, message=f"Switching to {info['name']}...",
        )
        settings.save_runtime_overrides({"active_model": key})
        result = start_server(key, hf_file=hf_file)
        return result
    finally:
        _set_download_state(
            active=False, status="idle" if is_server_running() else "error",
            model="", downloaded_bytes=0,
            message="" if is_server_running() else "Server failed to start.",
        )
        _download_lock.release()


def restart_server() -> bool:
    """
    Force-restart the server with the current active model.
    Always stops and restarts, even if the same key is active.
    Used by the Retry button.

    Respects _download_lock: refuses if a download lifecycle is active,
    and prevents concurrent retries from racing each other.
    Sets transient 'starting' state so UI shows "Booting up..." instead of "error".
    """
    if _external_server:
        logger.warning("Cannot restart — llama-server is managed externally")
        return False
    if not _download_lock.acquire(blocking=False):
        logger.warning("Lifecycle in progress, retry ignored")
        return False

    try:
        _clear_error_state()
        _set_download_state(
            active=True, model=settings.active_model, status="starting",
            downloaded_bytes=0, message="Restarting server...",
        )
        stop_server()
        result = start_server(settings.active_model, timeout=180)
        return result
    finally:
        _set_download_state(
            active=False, status="idle" if is_server_running() else "error",
            model="", downloaded_bytes=0,
            message="" if is_server_running() else "Server failed to start.",
        )
        _download_lock.release()


def get_active_model() -> Optional[str]:
    """Get the currently active model key."""
    return _active_model_key


def _owns_server() -> bool:
    """True if the llama-server process we spawned is alive."""
    return _server_process is not None and _server_process.poll() is None


def is_server_running() -> bool:
    """Check if llama-server is up and ready (ours or external).

    No network call: external state is kept current by sync_external_server()
    (startup + background watcher), so this is safe from async routes.
    """
    if _owns_server():
        return True
    return _external_server and not _external_loading


def get_model_status() -> dict:
    """
    Get the full model status for the frontend.

    Returns a dict with:
      status: "no_model" | "downloading" | "starting" | "ready" | "error"
      active_model: str | None
      capabilities: {audio: bool, vision: bool}
      download: dict | None  (download state if active)
    """
    dl = get_download_state()
    active = get_active_model() or settings.active_model
    caps = get_active_capabilities()
    external = _external_server and not _owns_server()

    # Check download/lifecycle state first (active=True means lifecycle in progress)
    if dl["active"]:
        return {
            "status": dl["status"],  # "downloading" or "starting"
            "active_model": active,
            "model_downloaded": is_model_downloaded(active),
            "capabilities": caps,
            "download": {
                "model": dl["model"],
                "downloaded_bytes": dl["downloaded_bytes"],
                "message": dl["message"],
                "status": dl["status"],
            },
        }

    # Sticky error from a failed download→start cycle (#4)
    if dl["status"] == "error":
        return {
            "status": "error",
            "active_model": active,
            "model_downloaded": is_model_downloaded(active),
            "capabilities": caps,
            "download": None,
            "message": dl["message"],
        }

    # External server still loading its model — it will be ready shortly
    if external and _external_loading:
        return {
            "status": "starting",
            "active_model": active,
            "model_downloaded": True,
            "external": True,
            "capabilities": caps,
            "download": None,
            "message": "External llama-server is loading a model...",
        }

    # No download in progress — check server
    if is_server_running():
        return {
            "status": "ready",
            "active_model": active,
            "model_downloaded": True,
            "external": external,
            "external_model": _external_model_name,
            "capabilities": caps,
            "download": None,
        }

    # Server not running — is a model at least downloaded?
    if is_model_downloaded(active):
        return {
            "status": "error",  # downloaded but server not running
            "active_model": active,
            "model_downloaded": True,
            "capabilities": caps,
            "download": None,
            "message": "Server not running. Click Retry to restart.",
        }

    # Check if ANY model is downloaded (active might be wrong)
    for m in AVAILABLE_MODELS:
        if is_model_downloaded(m["key"]):
            return {
                "status": "error",
                "active_model": active,
                "model_downloaded": True,
                "capabilities": caps,
                "download": None,
                "message": f"Model {m['key']} is downloaded but not active. Switch in Settings.",
            }

    return {
        "status": "no_model",
        "active_model": active,
        "model_downloaded": False,
        "capabilities": caps,
        "download": None,
    }


def _check_model_disk_space(key: str, quant: str = None) -> bool:
    """Check disk space before model download. Returns True if enough space."""
    info = get_model_info(key)
    if not info:
        return True

    # Use variant-specific file size if available, else estimate
    model_size = 5 * 1024**3  # default 5GB
    if quant:
        variant = next((v for v in info.get("variants", []) if v["quant"] == quant), None)
        if variant:
            # Parse "~7.5 GB" → bytes
            size_str = variant.get("file_size", "~5 GB")
            try:
                num = float(size_str.replace("~", "").replace("GB", "").strip())
                model_size = num * 1024**3
            except (ValueError, AttributeError):
                pass

    headroom = 1 * 1024**3  # 1GB headroom
    required = model_size + headroom

    try:
        usage = shutil.disk_usage(Path.home())
        if usage.free < required:
            free_gb = usage.free / (1024**3)
            need_gb = required / (1024**3)
            logger.warning(f"Low disk space! Free: {free_gb:.1f}GB, Need: ~{need_gb:.1f}GB")
            _set_download_state(
                status="error",
                message=f"Not enough disk space. Free: {free_gb:.1f}GB, Need: ~{need_gb:.1f}GB",
            )
            return False
        return True
    except Exception:
        return True  # If we can't check, don't block


def download_and_start(key: str, quant: str = None) -> bool:
    """
    Download a model, switch to it, and start the server.
    Used by the lock screen "Download" button.

    quant is locked in at the start and passed through the entire chain —
    never re-resolved from config mid-flight.

    Holds _download_lock across the ENTIRE lifecycle (download→start)
    so no second request can slip in between.

    Updates download state through: downloading → starting → ready/error.
    On failure, leaves error state sticky so the retry screen shows.
    """
    if not _download_lock.acquire(blocking=False):
        logger.warning(f"Lifecycle already in progress, rejecting {key}")
        return False

    try:
        # Clear any previous sticky error
        _clear_error_state()

        # Lock in variant at start — save preference if provided
        if quant:
            # Validate quant exists in model's variants
            info = get_model_info(key)
            if info and any(v["quant"] == quant for v in info.get("variants", [])):
                variants = dict(settings.model_variants)
                variants[key] = quant
                settings.save_runtime_overrides({"model_variants": variants})

        # Resolve ONCE — locked in for entire chain
        hf_file = get_effective_hf_file(key)
        active_quant = get_active_quant(key)

        # Disk space check with variant-specific size
        if not _check_model_disk_space(key, active_quant):
            return False

        # Download phase — pass locked-in params
        ok = _do_download(key, hf_file=hf_file, quant=active_quant)
        if not ok:
            # Error state is already set by _do_download — leave it sticky
            return False

        # An external server owns the port — keep using it. The download is
        # there for when ScreenMind manages llama-server itself again.
        if _external_server:
            logger.info(f"Downloaded {key}; not starting it — external llama-server in use")
            _set_download_state(
                active=False, status="idle", model=None,
                downloaded_bytes=0, message="",
            )
            return True

        # Transition to "starting" state
        _set_download_state(status="starting", message="Starting model server...")

        # Switch active model and start server with extended timeout
        settings.save_runtime_overrides({"active_model": key})
        started = start_server(key, timeout=180, hf_file=hf_file)  # 3 min for cold GGUF load

        if started:
            _set_download_state(
                active=False, status="idle", model=None,
                downloaded_bytes=0, message="",
            )
            return True
        else:
            # Leave error sticky
            _set_download_state(
                active=False, status="error",
                message="Server failed to start. Check GPU/VRAM.",
            )
            return False
    except Exception as e:
        _set_download_state(
            active=False, status="error",
            message=f"Unexpected error: {str(e)[:100]}",
        )
        return False
    finally:
        _download_lock.release()


# ── Delete functions ──────────────────────────────────────────────────

def delete_variant(key: str, quant: str) -> dict:
    """
    Delete a specific variant folder. Refuses if active or downloading.
    mmproj stays (shared per model). Clears stale config preference.
    """
    # Guard: refuse if active variant on running server
    if _active_model_key == key and get_active_quant(key) == quant:
        return {"ok": False, "error": "Cannot delete the active variant. Switch first."}
    # Guard: refuse if download in progress for this model
    dl_state = get_download_state()
    if dl_state["active"] and dl_state["model"] == key:
        return {"ok": False, "error": "Download in progress for this model"}

    variant_dir = _models_dir() / key / quant
    if variant_dir.exists():
        shutil.rmtree(variant_dir)
        # Clear stale preference if we just deleted the selected variant
        if settings.model_variants.get(key) == quant:
            variants = dict(settings.model_variants)
            del variants[key]
            settings.save_runtime_overrides({"model_variants": variants})
        logger.info(f"Deleted variant {key}/{quant}")
        return {"ok": True, "message": f"Deleted {quant}"}
    return {"ok": False, "error": "Variant not found"}


def delete_model(key: str) -> dict:
    """
    Delete ALL variant folders for a model. mmproj + .huggingface stay.
    Refuses if model is active or downloading. Clears stale config preference.
    """
    if _active_model_key == key:
        return {"ok": False, "error": "Cannot delete the active model. Switch first."}
    dl_state = get_download_state()
    if dl_state["active"] and dl_state["model"] == key:
        return {"ok": False, "error": "Download in progress for this model"}

    model_dir = _models_dir() / key
    if model_dir.exists():
        # Only delete variant subdirs (skip dotfiles like .huggingface, keep mmproj files)
        deleted = 0
        for child in model_dir.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                shutil.rmtree(child)
                deleted += 1
        # Clear stale preference
        if key in settings.model_variants:
            variants = dict(settings.model_variants)
            del variants[key]
            settings.save_runtime_overrides({"model_variants": variants})
        logger.info(f"Deleted {deleted} variant(s) for {key}")
        return {"ok": True, "message": f"Deleted {deleted} variant(s)"}
    return {"ok": False, "error": "Model not found"}

