"""
Screen Capture Module
Captures screenshots using mss (fastest cross-platform method).
On Wayland, delegates to WaylandScreenCapture (grim / XDG Portal).
Saves as JPEG with configurable quality to date-organized directories.
"""

import logging
import io
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import mss
import mss.tools
from PIL import Image

from screenmind.config import settings
from screenmind.platform_support import is_wayland

logger = logging.getLogger("screenmind.capture.screen")


class ScreenCapture:
    """Handles screenshot capture, compression, and storage.

    On Wayland Linux, delegates to WaylandScreenCapture (grim/XDG Portal).
    On X11/Windows/macOS, uses mss directly.
    """

    def __init__(self):
        self._backend = None
        self._sct = None

        if sys.platform == "linux" and is_wayland():
            try:
                from screenmind.capture.wayland import WaylandScreenCapture
                self._backend = WaylandScreenCapture()
            except Exception as e:
                logger.error(f"Wayland backend failed to init: {e}")
                logger.warning("Capture will be unavailable.")
                # self._backend stays None — capture() returns None gracefully
        else:
            self._sct = mss.MSS() if hasattr(mss, "MSS") else mss.mss()

    def _get_active_monitor(self) -> dict:
        """Return mss monitor dict for the monitor containing the active window.

        Platform-specific detection:
        - Windows: MonitorFromWindow API (handles DPI, spanning, minimized)
        - Linux X11: xdotool getwindowgeometry (center-point match)
        - macOS: Quartz CGWindowListCopyWindowInfo (center-point match)
        - Linux Wayland: Falls back to primary (Wayland hides window positions)

        Falls back to monitors[1] (primary) on any error.
        """
        monitors = self._sct.monitors
        if len(monitors) <= 2:
            return monitors[1]  # single monitor, nothing to detect

        try:
            if sys.platform == "win32":
                return self._detect_monitor_win32(monitors)

            # Linux X11 / macOS: get window center and match against monitors
            center = self._get_window_center()
            if center:
                cx, cy = center
                for mon in monitors[1:]:
                    if (mon["left"] <= cx < mon["left"] + mon["width"]
                            and mon["top"] <= cy < mon["top"] + mon["height"]):
                        logger.debug(
                            "Active monitor detected: %dx%d at (%d, %d)",
                            mon["width"], mon["height"],
                            mon["left"], mon["top"],
                        )
                        return mon
                logger.debug(
                    "Active window center (%d, %d) not in any monitor", cx, cy
                )
        except Exception as exc:
            logger.debug("Active monitor detection failed: %s", exc)

        return monitors[1]  # ultimate fallback

    # ── Platform-specific helpers ────────────────────────────────────────

    def _detect_monitor_win32(self, monitors: list) -> dict:
        """Windows: use MonitorFromWindow + GetMonitorInfoW."""
        import ctypes
        from ctypes import wintypes

        MONITOR_DEFAULTTOPRIMARY = 1
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        hmonitor = ctypes.windll.user32.MonitorFromWindow(
            hwnd, MONITOR_DEFAULTTOPRIMARY
        )

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not ctypes.windll.user32.GetMonitorInfoW(
            hmonitor, ctypes.byref(mi)
        ):
            return monitors[1]

        target_left = mi.rcMonitor.left
        target_top = mi.rcMonitor.top

        for mon in monitors[1:]:
            if mon["left"] == target_left and mon["top"] == target_top:
                logger.debug(
                    "Active monitor detected: %dx%d at (%d, %d)",
                    mon["width"], mon["height"],
                    mon["left"], mon["top"],
                )
                return mon

        logger.debug("Active monitor not matched in mss list, using primary")
        return monitors[1]

    def _get_window_center(self) -> Optional[Tuple[int, int]]:
        """Get the center point (x, y) of the active window.

        Returns None if detection is unavailable (e.g. Wayland).
        """
        if sys.platform == "darwin":
            return self._window_center_macos()
        elif sys.platform == "linux":
            return self._window_center_linux()
        return None

    def _window_center_linux(self) -> Optional[Tuple[int, int]]:
        """Linux X11: use xdotool to get active window geometry."""
        import subprocess

        result = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowgeometry", "--shell"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode != 0:
            return None

        # Output format: WINDOW=...\nX=...\nY=...\nWIDTH=...\nHEIGHT=...
        vals = {}
        for line in result.stdout.strip().splitlines():
            if "=" in line:
                key, val = line.split("=", 1)
                vals[key] = int(val)

        if "X" in vals and "Y" in vals and "WIDTH" in vals and "HEIGHT" in vals:
            cx = vals["X"] + vals["WIDTH"] // 2
            cy = vals["Y"] + vals["HEIGHT"] // 2
            return cx, cy
        return None

    def _window_center_macos(self) -> Optional[Tuple[int, int]]:
        """macOS: use Quartz to get frontmost window bounds.

        The window list is ordered front to back, so the first layer-0 window
        is the active one. (NSWorkspace.frontmostApplication() goes stale in a
        process without an NSRunLoop, so we don't use it to pick the app.)
        """
        from Quartz import (  # type: ignore
            CGWindowListCopyWindowInfo,
            kCGWindowListOptionOnScreenOnly,
            kCGWindowListExcludeDesktopElements,
            kCGNullWindowID,
        )

        windows = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
            kCGNullWindowID,
        )
        for win in windows or []:
            if win.get("kCGWindowLayer", -1) == 0:
                bounds = win.get("kCGWindowBounds", {})
                x = int(bounds.get("X", 0))
                y = int(bounds.get("Y", 0))
                w = int(bounds.get("Width", 0))
                h = int(bounds.get("Height", 0))
                if w > 0 and h > 0:
                    return x + w // 2, y + h // 2
        return None

    def _select_monitor(self) -> dict:
        """Pick the monitor to capture based on settings."""
        if settings.capture_active_monitor:
            mon = self._get_active_monitor()
        else:
            mon = self._sct.monitors[1]
        self._last_monitor_key = f"{mon['left']},{mon['top']}"
        return mon

    @property
    def last_monitor_key(self) -> Optional[str]:
        """Key identifying the last captured monitor (e.g. '0,0'), or None."""
        return getattr(self, "_last_monitor_key", None)

    def capture(self) -> Optional[Tuple[Path, Image.Image]]:
        """
        Capture a screenshot and save as a compressed JPEG.

        Returns:
            Tuple of (saved file path, PIL Image) or None if capture fails.
        """
        if self._backend:
            return self._backend.capture()

        if self._sct:
            try:
                # Grab the target monitor (primary by default, active if Beta enabled)
                monitor = self._select_monitor()
                raw = self._sct.grab(monitor)

                # Convert to PIL Image (mss returns BGRA, PIL expects RGB)
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

                # Save to date-organized directory
                now = datetime.now()
                date_dir = settings.screenshots_dir / now.strftime("%Y-%m-%d")
                date_dir.mkdir(parents=True, exist_ok=True)

                filename = f"{now.strftime('%H-%M-%S')}_{int(now.timestamp() * 1000) % 1000:03d}.jpg"
                filepath = date_dir / filename

                img.save(
                    str(filepath),
                    "JPEG",
                    quality=settings.screenshot_quality,
                    optimize=True,
                )

                # Encrypt at rest if enabled (no-op when encryption_enabled=False)
                try:
                    from screenmind.privacy.encryption import encrypt_image
                    encrypt_image(filepath)
                except Exception:
                    pass  # Never fail capture due to encryption

                return filepath, img

            except Exception as e:
                logger.error(f"Error capturing screenshot: {e}")
                return None

        return None  # both _backend and _sct are None (init failure)

    def capture_to_bytes(self) -> Optional[Tuple[bytes, Image.Image]]:
        """
        Capture screenshot and return as JPEG bytes (for immediate processing
        without saving to disk first).

        Returns:
            Tuple of (JPEG bytes, PIL Image) or None if capture fails.
        """
        if self._backend:
            return self._backend.capture_to_bytes()

        if self._sct:
            try:
                monitor = self._select_monitor()
                raw = self._sct.grab(monitor)
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

                buffer = io.BytesIO()
                img.save(
                    buffer,
                    "JPEG",
                    quality=settings.screenshot_quality,
                    optimize=True,
                )
                return buffer.getvalue(), img

            except Exception as e:
                logger.error(f"Error capturing to bytes: {e}")
                return None

        return None

    def close(self):
        """Release capture resources."""
        if self._backend:
            self._backend.close()
        elif self._sct:
            self._sct.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

