"""
Wayland Screenshot Backend
Tries grim first, falls back to XDG Desktop Portal.
No compositor allowlist — runtime failure counter handles tier selection.
"""

import logging
import io
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

from screenmind.config import settings

logger = logging.getLogger("screenmind.capture.wayland")


class WaylandScreenCapture:
    """Wayland screenshot backend. Tries grim first, falls back to XDG Portal.

    Tier selection: grim is tried if present (shutil.which). If it works (any
    wlroots compositor — Sway, Hyprland, Niri, river, Wayfire, labwc, forks),
    great. If it fails 3 times consecutively (GNOME/KDE — grim exits non-zero
    instantly, sub-second total cost), the counter triggers a portal fallback.
    If portal succeeds, grim is permanently disabled for the session. If portal
    is unavailable, the counter resets and grim keeps trying.

    Thread safety: all capture methods use subprocess (no persistent handles).
    Do NOT cache D-Bus connections or add persistent state — this must remain
    safe to call from run_in_executor if needed in the future.
    """

    def __init__(self):
        self._portal_available = False  # bool — proxy is rebuilt per capture
        self._error_logged = False
        self._grim_failures = 0        # consecutive grim failures
        self._grim_disabled = False    # permanently disabled only when portal takes over
        self._grim_error_logged = False # one-shot: suppress repeated grim stderr

        # Focused output cache (1s TTL — re-detects per capture)
        self._cached_output = None
        self._cached_output_ts = 0.0
        self._compositor = self._detect_compositor()

        # No compositor allowlist — try grim if present, let the failure counter
        # handle non-wlroots compositors (3 fast failures → portal switch).
        self._has_grim = shutil.which("grim") is not None

        if self._has_grim:
            logger.info(f"Wayland: grim found (compositor: {self._compositor or 'unknown'})")
        else:
            self._portal_available = self._check_portal()
            if self._portal_available:
                logger.info("Wayland: using XDG Portal (may prompt for permission)")
            else:
                logger.info("Wayland: no capture method available.")
                logger.info("Install grim: sudo pacman -S grim  (or apt install grim)")
                logger.info("Or ensure xdg-desktop-portal is running + python3-gi installed")

    def _detect_compositor(self) -> Optional[str]:
        """Detect compositor type (cached at init — doesn't change at runtime)."""
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            return "hyprland"
        if os.environ.get("SWAYSOCK"):
            return "sway"
        if os.environ.get("NIRI_SOCKET"):
            return "niri"
        return None

    # ── Shared grab ─────────────────────────────────────────────────

    def _grab(self) -> Optional[Image.Image]:
        """Capture and return a raw PIL Image. No save, no encrypt.

        Runtime fallback: after 3 consecutive grim failures, tries portal.
        Only permanently disables grim if portal fallback succeeds — a transient
        grim fluke on wlroots+grim (no portal) doesn't kill capture for the session.
        """
        if self._has_grim and not self._grim_disabled:
            result = self._grab_grim()
            if result is not None:
                self._grim_failures = 0  # reset on success
                return result
            self._grim_failures += 1
            if self._grim_failures >= 3:
                # 3 consecutive failures — try portal fallback
                logger.error(f"grim failed {self._grim_failures}x — trying XDG Portal")
                if not self._portal_available:
                    self._portal_available = self._check_portal()
                if self._portal_available:
                    portal_result = self._grab_portal()
                    if portal_result is not None:
                        # Portal works — permanently switch away from grim
                        self._grim_disabled = True
                        logger.info("Switched to XDG Portal permanently")
                        return portal_result
                # Portal unavailable or failed — keep trying grim
                # (don't latch _grim_disabled, just reset counter)
                self._grim_failures = 0
            return None  # this capture failed, but grim stays active
        elif self._portal_available:
            return self._grab_portal()
        if not self._error_logged:
            logger.debug("No Wayland capture method available. Skipping.")
            self._error_logged = True
        return None

    # ── Public API (matches ScreenCapture interface) ────────────────

    def grab(self) -> Optional[Image.Image]:
        """Capture screenshot into memory (no save, no encrypt).

        ScreenCapture saves it (save_screenshot) once the capture worker
        has deduped it.
        """
        return self._grab()

    def capture_to_bytes(self) -> Optional[Tuple[bytes, Image.Image]]:
        """Capture screenshot, return as (JPEG bytes, PIL.Image)."""
        img = self._grab()
        if img is None:
            return None
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=settings.screenshot_quality, optimize=True)
        return buf.getvalue(), img

    def close(self):
        """No persistent resources to clean up (subprocess-based)."""
        pass

    # ── grim (Tier 1) ──────────────────────────────────────────────

    def _grab_grim(self) -> Optional[Image.Image]:
        """Capture via grim stdout pipe. No temp file on disk."""
        cmd = ["grim"]
        output = self._get_focused_output()
        if output:
            cmd += ["-o", output]
        cmd.append("-")  # write PNG to stdout

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            if result.returncode != 0:
                if not self._grim_error_logged:
                    logger.error(f"grim failed: {result.stderr.decode()[:200]}")
                    self._grim_error_logged = True
                return None
            return Image.open(io.BytesIO(result.stdout)).convert("RGB")
        except subprocess.TimeoutExpired:
            if not self._grim_error_logged:
                logger.info("grim timed out")
                self._grim_error_logged = True
            return None
        except Exception as e:
            if not self._grim_error_logged:
                logger.error(f"grim error: {e}")
                self._grim_error_logged = True
            return None

    def _get_focused_output(self) -> Optional[str]:
        """Get focused output name, cached for 1 second."""
        now = time.time()
        if now - self._cached_output_ts < 1.0:
            return self._cached_output
        self._cached_output = self._detect_focused_output()
        self._cached_output_ts = now
        return self._cached_output

    def _detect_focused_output(self) -> Optional[str]:
        """Ask compositor for its currently focused output name."""
        try:
            if self._compositor == "hyprland":
                result = subprocess.run(
                    ["hyprctl", "monitors", "-j"],
                    capture_output=True, text=True, timeout=2
                )
                if result.returncode == 0:
                    for m in json.loads(result.stdout):
                        if m.get("focused"):
                            return m.get("name")

            elif self._compositor == "sway":
                result = subprocess.run(
                    ["swaymsg", "-t", "get_outputs"],
                    capture_output=True, text=True, timeout=2
                )
                if result.returncode == 0:
                    for o in json.loads(result.stdout):
                        if o.get("focused"):
                            return o.get("name")

            elif self._compositor == "niri":
                # Niri: schema varies by version — verify on target (issue #5)
                result = subprocess.run(
                    ["niri", "msg", "--json", "outputs"],
                    capture_output=True, text=True, timeout=2
                )
                if result.returncode == 0:
                    outputs = json.loads(result.stdout)
                    if isinstance(outputs, dict):
                        for name, info in outputs.items():
                            if isinstance(info, dict) and info.get("is_focused"):
                                return name
                        if outputs:
                            return next(iter(outputs))
        except Exception:
            pass

        return None  # grim captures all outputs stitched

    # ── XDG Portal (Tier 2) ────────────────────────────────────────

    def _check_portal(self) -> bool:
        """Check if XDG Portal screenshot is available. Soft check —
        DBusProxy.new_sync can succeed for activatable services not running."""
        try:
            from gi.repository import Gio, GLib  # noqa: F401
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            proxy = Gio.DBusProxy.new_sync(
                bus, Gio.DBusProxyFlags.NONE, None,
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.Screenshot", None
            )
            return proxy is not None
        except Exception:
            return False

    def _grab_portal(self) -> Optional[Image.Image]:
        """Capture via XDG Desktop Portal (async Request/Response handshake).

        WARNING: Blocks for up to 5s (MainContext.iteration loop).
        On GNOME, shows a permission dialog on EVERY capture.
        No persistent D-Bus handles — thread-safe by construction.
        """
        try:
            from gi.repository import Gio, GLib
        except ImportError:
            logger.warning("python-gi not available for portal capture")
            self._portal_available = False
            return None

        import uuid
        result_holder = {"uri": None, "done": False}
        handle_token = "screenmind_" + uuid.uuid4().hex[:8]

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        sender = bus.get_unique_name().replace(":", "").replace(".", "_")
        response_path = f"/org/freedesktop/portal/desktop/request/{sender}/{handle_token}"

        def on_response(conn, sender_name, path, iface, signal, params):
            response_code, results = params.unpack()
            if response_code == 0:
                result_holder["uri"] = results.get("uri", "")
            result_holder["done"] = True

        # Subscribe BEFORE call — no race
        sub_id = bus.signal_subscribe(
            "org.freedesktop.portal.Desktop",
            "org.freedesktop.portal.Request", "Response",
            response_path, None, Gio.DBusSignalFlags.NONE, on_response
        )

        try:
            proxy = Gio.DBusProxy.new_sync(
                bus, Gio.DBusProxyFlags.NONE, None,
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.Screenshot", None
            )
            options = GLib.Variant("a{sv}", {
                "handle_token": GLib.Variant("s", handle_token)
            })
            proxy.call_sync(
                "Screenshot",
                GLib.Variant("(sa{sv})", ("", options)),
                0, 5000, None
            )

            # Spin GLib main context until response or timeout
            ctx = GLib.MainContext.default()
            deadline = time.time() + 5.0
            while not result_holder["done"] and time.time() < deadline:
                ctx.iteration(False)
                time.sleep(0.05)

            if not result_holder["uri"]:
                logger.info("Portal: no URI received (cancelled or timed out)")
                return None

            # Parse file:// URI → local path
            uri = result_holder["uri"]
            portal_path = Path(uri[7:]) if uri.startswith("file://") else Path(uri)

            if not portal_path.exists():
                logger.warning(f"Portal: file not found: {portal_path}")
                return None

            # Load image, force pixel read, then delete portal temp file
            img = Image.open(portal_path).convert("RGB")
            img.load()

            try:
                portal_path.unlink()
            except Exception:
                pass

            return img

        except Exception as e:
            logger.error(f"Portal error: {e}")
            return None
        finally:
            bus.signal_unsubscribe(sub_id)
