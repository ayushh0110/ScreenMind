"""
macOS Platform Adapter
Uses Quartz (CGWindowListCopyWindowInfo) for window detection.
Accessibility via AXUIElement (requires accessibility permission).
"""

import logging
import time
from typing import Optional, Tuple

from screenmind.platform_support.base import PlatformAdapter

logger = logging.getLogger("screenmind.platform_support.macos")

# One capture cycle asks for the app name, title, PID and bounds separately.
# Caching the Quartz snapshot briefly makes them all describe the same window.
_FRONT_WINDOW_TTL = 1.0

# Windows smaller than this (in points) are overlay helpers such as window
# managers (Rectangle) or menu-bar popovers, not the window the user works in.
_MIN_WINDOW_SIZE = 50


class MacOSAdapter(PlatformAdapter):
    """macOS implementation using Quartz (pyobjc) and AXUIElement."""

    def __init__(self):
        self._ax_available = False
        self._front_cache: Optional[dict] = None
        self._front_cache_ts = float("-inf")
        self._init_frameworks()

    def _init_frameworks(self):
        """Try to import macOS frameworks."""
        try:
            from ApplicationServices import (  # type: ignore
                AXUIElementCreateSystemWide,
                AXUIElementCopyAttributeValue,
            )
            self._ax_available = True
            logger.debug("macOS Accessibility initialized")
        except ImportError:
            logger.warning("macOS Accessibility not available (install pyobjc-framework-ApplicationServices)")

    @property
    def platform_name(self) -> str:
        return "macOS"

    def _front_window(self) -> Optional[dict]:
        """Frontmost window, cached for _FRONT_WINDOW_TTL seconds."""
        now = time.monotonic()
        if now - self._front_cache_ts >= _FRONT_WINDOW_TTL:
            self._front_cache = self._query_front_window()
            self._front_cache_ts = now
        return self._front_cache

    def _query_front_window(self) -> Optional[dict]:
        """Return the frontmost normal window from Quartz (owner, pid, title, bounds).

        NSWorkspace.frontmostApplication() goes stale in a process without an
        NSRunLoop, so we read the live on-screen window list instead. It is
        ordered front to back; layer 0 is the normal app window layer.
        kCGWindowName needs Screen Recording permission, else it is empty.
        """
        try:
            import Quartz  # type: ignore
            windows = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
                Quartz.kCGNullWindowID,
            ) or []
            for w in windows:
                if w.get("kCGWindowLayer", 1) != 0:
                    continue
                bounds = w.get("kCGWindowBounds") or {}
                if (bounds.get("Width", 0) < _MIN_WINDOW_SIZE
                        or bounds.get("Height", 0) < _MIN_WINDOW_SIZE):
                    continue
                return {
                    "owner": w.get("kCGWindowOwnerName"),
                    "pid": w.get("kCGWindowOwnerPID"),
                    "title": w.get("kCGWindowName") or None,
                    "bounds": (
                        int(bounds.get("X", 0)), int(bounds.get("Y", 0)),
                        int(bounds["Width"]), int(bounds["Height"]),
                    ),
                }
        except Exception as e:
            logger.debug(f"Quartz window lookup failed: {e}")
        return None

    def get_foreground_window_handle(self) -> Optional[int]:
        """macOS doesn't use integer window handles like Win32. Returns PID instead."""
        front = self._front_window()
        return front["pid"] if front else None

    def get_active_window_title(self) -> Optional[str]:
        """Get the frontmost window's title, falling back to the app name."""
        front = self._front_window()
        if front:
            return front["title"] or front["owner"]
        return None

    def get_active_app_name(self) -> Optional[str]:
        """Get the app that owns the frontmost window."""
        front = self._front_window()
        return front["owner"] if front else None

    def get_active_window_bounds(self) -> Optional[Tuple[int, int, int, int]]:
        """Frontmost window as (x, y, width, height) in global screen points."""
        front = self._front_window()
        return front["bounds"] if front else None

    # ── Accessibility ────────────────────────────────────────────────

    def is_a11y_available(self) -> bool:
        return self._ax_available

    @property
    def trusts_os_app_name(self) -> bool:
        """The window owner name ("Terminal", "Google Chrome") is user-facing, while
        titles rarely end with the app name (Terminal: "dir — cmd — 120×30")."""
        return True

    def extract_a11y_text(self, hwnd: Optional[int] = None) -> Tuple[Optional[str], str]:
        """
        Extract accessible text using macOS Accessibility API (AXUIElement).
        Requires user to grant accessibility permission in System Preferences.
        """
        if not self._ax_available:
            return None, "none"

        try:
            import Quartz  # type: ignore
            from ApplicationServices import (  # type: ignore
                AXUIElementCreateApplication,
                AXUIElementCopyAttributeValue,
                kAXFocusedWindowAttribute,
                kAXChildrenAttribute,
                kAXValueAttribute,
                kAXTitleAttribute,
                kAXRoleAttribute,
            )

            # Get focused app PID
            pid = hwnd or self.get_foreground_window_handle()
            if not pid:
                return None, "none"

            app_ref = AXUIElementCreateApplication(pid)

            # Get focused window
            err, window = AXUIElementCopyAttributeValue(app_ref, kAXFocusedWindowAttribute, None)
            if err or not window:
                return None, "none"

            texts = []
            self._walk_ax_tree(window, texts, depth=0, max_depth=8)

            if texts:
                result = '\n'.join(texts)
                if len(result.strip()) > 20:
                    logger.debug(f"macOS: Extracted {len(texts)} elements")
                    return result.strip(), "a11y"

            return None, "none"

        except Exception as e:
            logger.error(f"macOS extraction failed: {e}")
            return None, "none"

    def _walk_ax_tree(self, element, texts: list, depth: int, max_depth: int = 8):
        """Walk the AXUIElement tree to extract text."""
        if depth > max_depth or len(texts) > 500:
            return

        try:
            from ApplicationServices import (  # type: ignore
                AXUIElementCopyAttributeValue,
                kAXChildrenAttribute,
                kAXValueAttribute,
                kAXTitleAttribute,
            )

            # Get title
            err, title = AXUIElementCopyAttributeValue(element, kAXTitleAttribute, None)
            if not err and title and str(title).strip():
                text = str(title).strip()
                if len(text) > 1 and text not in texts[-5:]:
                    texts.append(text)

            # Get value (for text fields, etc.)
            err, value = AXUIElementCopyAttributeValue(element, kAXValueAttribute, None)
            if not err and value and str(value).strip():
                val_text = str(value).strip()
                if len(val_text) > 1 and val_text != str(title or ""):
                    texts.append(val_text)

            # Recurse into children
            err, children = AXUIElementCopyAttributeValue(element, kAXChildrenAttribute, None)
            if not err and children:
                for child in children:
                    self._walk_ax_tree(child, texts, depth + 1, max_depth)

        except Exception:
            pass
