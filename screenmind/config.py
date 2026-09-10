"""
ScreenMind Configuration
Centralized settings using pydantic-settings. 
All values can be overridden via .env file or environment variables.
Runtime changes (from dashboard) are persisted to settings.json.
"""

import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import List, Literal, Optional

from pydantic_settings import BaseSettings
from pydantic import Field, ValidationError



# ── Logging Setup ────────────────────────────────────────────────────────────

def _setup_logging():
    """Configure screenmind logger hierarchy. Safe to call multiple times.

    Environment variables:
        SCREENMIND_LOG_LEVEL: DEBUG, INFO (default), WARNING, ERROR
        SCREENMIND_LOG_FILE:  Optional path to a log file (rotating, 10MB x 3 backups)
    """
    root = logging.getLogger("screenmind")
    if root.handlers:
        return
    level = os.environ.get("SCREENMIND_LOG_LEVEL", "INFO")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Always log to stderr (unless running under pythonw where stderr is None)
    if sys.stderr is not None:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(fmt)
        root.addHandler(stderr_handler)

    # Optionally log to a rotating file
    log_file = os.environ.get("SCREENMIND_LOG_FILE")
    # Auto-enable file logging when stderr is unavailable (pythonw.exe)
    if not log_file and sys.stderr is None:
        _data = os.environ.get("SCREENMIND_DATA_DIR", os.path.join(os.path.expanduser("~"), ".screenmind"))
        os.makedirs(_data, exist_ok=True)
        log_file = os.path.join(_data, "screenmind.log")
    if log_file:
        try:
            from logging.handlers import RotatingFileHandler
            file_handler = RotatingFileHandler(
                log_file, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8",
            )
            file_handler.setFormatter(fmt)
            root.addHandler(file_handler)
        except (OSError, PermissionError) as e:
            # Invalid path or no write permission — continue with stderr only
            root.warning(f"Could not open log file '{log_file}': {e}")

_setup_logging()

logger = logging.getLogger("screenmind.config")

# Settings keys that can be overridden at runtime (from dashboard or settings.json)
_ALLOWED_OVERRIDES = {
    "capture_interval", "performance_mode",
    "context_window", "kv_cache_quant", "flash_attention",
    "analysis_mode",
    "auto_pause_heavy_apps", "heavy_apps",
    "defer_analysis", "meeting_transcription",
    "meeting_apps",
    "active_model", "model_variants", "retention_days",
    "obsidian_enabled", "obsidian_vault_path",
    "notion_enabled", "notion_token", "notion_database_id",
    "webhook_enabled", "webhook_url", "webhook_events", "webhook_secret", "webhook_headers",
    "webhook_extra",
    "smart_notifications", "distraction_minutes", "break_reminder_minutes",
    "auto_bookmark", "auto_bookmark_keywords",
    "agents_enabled", "agents_auto_run_python",
    "sensitive_filter_enabled", "sensitive_filter_types",
    "dashboard_pin_hash", "dashboard_lock_timeout",
    "encryption_enabled",
    "bookmark_hotkey", "pause_hotkey", "voice_hotkey",
    "capture_active_monitor",
    "setup_complete",
    "capture_paused",
}

# Lock to prevent concurrent read-modify-write races on settings.json
_settings_lock = threading.Lock()

class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    # ── Capture ──────────────────────────────────────────────────────────
    capture_interval: int = Field(
        default=40,
        description="Seconds between screenshot captures",
        ge=10,
        le=120,
    )
    screenshot_quality: int = Field(
        default=70,
        description="JPEG quality (1-100). 70 balances size vs readability",
        ge=10,
        le=100,
    )
    data_dir: str = Field(
        default="~/.screenmind",
        description="Root directory for all ScreenMind data",
    )
    capture_active_monitor: bool = Field(
        default=False,
        description="(Beta) Capture the monitor with the active window instead of primary",
    )
    capture_paused: bool = Field(
        default=True,
        description="Persisted capture state. True = paused (default for fresh installs), False = capturing.",
    )

    # ── Model ────────────────────────────────────────────────────────────
    gemma_mode: Literal["local", "api"] = Field(
        default="local",
        description="'local' for llama-server, 'api' for Google AI Studio (sends data to Google)",
    )
    ollama_model: str = Field(
        default="gemma4:e2b",
        description="Model identifier (legacy field, kept for settings.json compat)",
    )
    active_model: str = Field(
        default="gemma-4-e2b",
        description="Active model key for llama-server",
    )
    model_variants: dict = Field(
        default_factory=dict,
        description="Per-model variant selection, e.g. {'gemma-4-e2b': 'Q8_0'}",
    )
    ollama_host: str = Field(
        default="http://localhost:11434",
        description="Legacy Ollama host (unused, kept for compat)",
    )
    llama_server_host: str = Field(
        default="http://127.0.0.1:5809",
        description="llama-server URL",
    )
    llama_server_port: int = Field(
        default=5809,
        description="llama-server port",
    )
    google_api_key: Optional[str] = Field(
        default=None,
        description="Google AI Studio API key (for api mode)",
    )

    # ── Developer Context ────────────────────────────────────────────────
    workspace_dirs: str = Field(
        default="~/Projects,~/Desktop",
        description="Comma-separated directories to scan for git repos",
    )

    # ── Privacy ──────────────────────────────────────────────────────────
    blocked_apps: str = Field(
        default="",
        description="Comma-separated app names to skip (privacy zones)",
    )

    # ── Hotkey ───────────────────────────────────────────────────────────
    bookmark_hotkey: str = Field(
        default="ctrl+shift+b",
        description="Hotkey combo to bookmark current moment",
    )
    pause_hotkey: str = Field(
        default="ctrl+shift+p",
        description="Hotkey combo to pause/resume capture",
    )
    voice_hotkey: str = Field(
        default="ctrl+shift+v",
        description="Hotkey combo for voice memo (hold to record)",
    )

    # ── Resource Management ──────────────────────────────────────────────
    performance_mode: Literal["minimal", "balanced", "maximum"] = Field(
        default="balanced",
        description="'minimal' (CPU-heavy, saves VRAM), 'balanced' (default), 'maximum' (full GPU)",
    )
    context_window: int = Field(
        default=6144,
        description="Context window size for llama-server (-c flag). Lower saves VRAM.",
        ge=2048,
        le=16384,
    )
    analysis_mode: Literal["fast", "balanced", "merged"] = Field(
        default="fast",
        description="'fast' (~12s, no thinking), 'balanced' (~40s, thinking), or 'merged' (~76s, thinking+layout)",
    )
    kv_cache_quant: bool = Field(
        default=False,
        description="Enable KV cache quantization (saves ~200MB VRAM but adds ~10s per inference)",
    )
    flash_attention: bool = Field(
        default=True,
        description="Enable flash attention (faster, less VRAM). Disable if GPU doesn't support it.",
    )
    auto_pause_heavy_apps: bool = Field(
        default=True,
        description="Auto-pause capture when heavy apps (games, editors) are in foreground",
    )
    heavy_apps: str = Field(
        default="game,valorant,fortnite,minecraft,unity,unreal,premiere,resolve,blender,obs,davinci",
        description="Comma-separated substrings to match against foreground app names",
    )
    defer_analysis: bool = Field(
        default=False,
        description="When ON, queue screenshots and analyze only when idle (60s no new captures)",
    )

    # ── Meeting Transcription ────────────────────────────────────────────
    meeting_transcription: bool = Field(
        default=False,
        description="Enable auto-transcription when meeting apps are detected",
    )
    meeting_apps: str = Field(
        default="zoom,teams,meet,webex,slack,discord",
        description="Comma-separated app substrings that indicate a meeting",
    )
    # ── Integrations ─────────────────────────────────────────────────────
    obsidian_enabled: bool = Field(default=False, description="Auto-export summaries to Obsidian vault")
    obsidian_vault_path: str = Field(default="", description="Absolute path to Obsidian vault folder")

    notion_enabled: bool = Field(default=False, description="Auto-export summaries to Notion")
    notion_token: str = Field(default="", description="Notion internal integration token")
    notion_database_id: str = Field(default="", description="Notion database ID for summaries")

    webhook_enabled: bool = Field(default=False, description="Fire HTTP POST on events")
    webhook_url: str = Field(default="", description="Comma-separated webhook target URLs")
    webhook_events: str = Field(default="daily_summary,bookmark,meeting_end", description="Comma-separated event types")
    webhook_secret: str = Field(default="", description="Optional HMAC secret for webhook signing")
    webhook_headers: str = Field(default="", description="Custom headers as Key: Value lines")
    webhook_extra: str = Field(default="[]", description="JSON array of extra named webhook profiles")

    # ── Smart Notifications ──────────────────────────────────────────────
    smart_notifications: bool = Field(default=True, description="Enable smart usage notifications")
    distraction_minutes: int = Field(default=45, description="Alert after N minutes on entertainment apps")
    break_reminder_minutes: int = Field(default=90, description="Remind to take break after N minutes")

    # ── Auto-Tagging ─────────────────────────────────────────────────────
    auto_bookmark: bool = Field(default=True, description="Auto-bookmark important moments")
    auto_bookmark_keywords: str = Field(default="git push,deploy,npm run build,docker,merge,pull request", description="Keywords that trigger auto-bookmark")

    # ── Agents ────────────────────────────────────────────────────────────
    agents_enabled: bool = Field(default=False, description="Enable the agent/plugin system")
    agents_auto_run_python: bool = Field(default=False, description="Run Python plugins without confirmation (default: ask)")

    # ── Privacy & Security ────────────────────────────────────────────────
    sensitive_filter_enabled: bool = Field(default=True, description="Filter sensitive data (credit cards, SSNs, API keys) from captured text")
    sensitive_filter_types: str = Field(default="credit_card,ssn,api_key,jwt,password", description="Comma-separated filter types")
    dashboard_pin_hash: str = Field(default="", description="SHA-256 hash of dashboard PIN (empty = no lock)")
    dashboard_lock_timeout: int = Field(default=30, description="Minutes before dashboard auto-locks")
    encryption_enabled: bool = Field(default=False, description="Encrypt screenshots at rest (AES via OS keyring)")

    # ── Data Retention ───────────────────────────────────────────────────
    retention_days: int = Field(
        default=7,
        description="Auto-delete timeline data older than N days. 0 = keep forever.",
        ge=0,
        le=365,
    )

    # ── Server ───────────────────────────────────────────────────────────
    api_host: str = Field(default="127.0.0.1", description="API bind host")
    api_port: int = Field(default=7777, description="API bind port")

    # ── Internal State ────────────────────────────────────────────────────
    setup_complete: bool = Field(default=False, description="Whether first-run setup is complete")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "validate_assignment": True,
    }

    # ── Derived Paths ────────────────────────────────────────────────────

    @property
    def data_path(self) -> Path:
        """Resolved, absolute data directory path."""
        return Path(os.path.expanduser(self.data_dir)).resolve()

    @property
    def screenshots_dir(self) -> Path:
        """Directory where screenshots are stored, organized by date."""
        return self.data_path / "screenshots"

    @property
    def db_path(self) -> Path:
        """SQLite database file path."""
        return self.data_path / "screenmind.db"

    @property
    def settings_json_path(self) -> Path:
        """Path to runtime settings override file."""
        return self.data_path / "settings.json"

    @property
    def workspace_dirs_list(self) -> List[str]:
        """Parsed list of workspace directories."""
        if not self.workspace_dirs:
            return []
        return [
            os.path.expanduser(d.strip())
            for d in self.workspace_dirs.split(",")
            if d.strip()
        ]

    @property
    def blocked_apps_list(self) -> List[str]:
        """Parsed list of blocked app names."""
        if not self.blocked_apps:
            return []
        return [a.strip().lower() for a in self.blocked_apps.split(",") if a.strip()]

    @property
    def heavy_apps_list(self) -> List[str]:
        """Parsed list of heavy app substrings for auto-pause."""
        if not self.heavy_apps:
            return []
        return [a.strip().lower() for a in self.heavy_apps.split(",") if a.strip()]

    @property
    def meeting_apps_list(self) -> List[str]:
        """Parsed list of meeting app substrings."""
        if not self.meeting_apps:
            return []
        return [a.strip().lower() for a in self.meeting_apps.split(",") if a.strip()]

    @property
    def num_gpu_layers(self) -> int:
        """Map performance_mode to GPU layers for llama-server (-ngl flag)."""
        mode_map = {"minimal": 0, "balanced": 15, "maximum": 99}
        return mode_map.get(self.performance_mode, 15)

    def ensure_dirs(self):
        """Create all required directories if they don't exist."""
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    def load_runtime_overrides(self):
        """Load settings.json overrides (from dashboard changes)."""
        path = self.settings_json_path
        if path.exists():
            try:
                with _settings_lock:
                    overrides = json.loads(path.read_text())
                for k, v in overrides.items():
                    if k in _ALLOWED_OVERRIDES and hasattr(self, k):
                        try:
                            setattr(self, k, v)
                        except (ValueError, ValidationError):
                            logger.warning("Invalid override ignored: %s=%r", k, v)
                logger.info(f"Loaded runtime overrides: {list(overrides.keys())}")
            except Exception as e:
                logger.error(f"Failed to load settings.json: {e}")

    def save_runtime_overrides(self, updates: dict):
        """Save dashboard settings to settings.json."""
        with _settings_lock:
            path = self.settings_json_path
            existing = {}
            if path.exists():
                try:
                    existing = json.loads(path.read_text())
                except Exception as e:
                    logger.debug("Could not read existing settings.json: %s", e)
            for k, v in updates.items():
                if k in _ALLOWED_OVERRIDES:
                    existing[k] = v
                    if hasattr(self, k):
                        try:
                            setattr(self, k, v)
                        except (ValueError, ValidationError) as e:
                            logger.debug("Override not applied in memory: %s=%r, %s", k, v, e)
            path.write_text(json.dumps(existing, indent=2))


# Singleton instance
settings = Settings()
# Load runtime overrides from settings.json (if any)
settings.load_runtime_overrides()
