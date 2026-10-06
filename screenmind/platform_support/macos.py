"""
macOS Platform Adapter
Uses AppKit/NSWorkspace for window detection.
Accessibility via AXUIElement (requires accessibility permission).
"""

import logging
import subprocess
from typing import Optional, Tuple

from screenmind.platform_support.base import PlatformAdapter

logger = logging.getLogger("screenmind.platform_support.macos")


class MacOSAdapter(PlatformAdapter):
    """macOS implementation using AppKit (pyobjc) and AXUIElement."""

    def __init__(self):
        self._appkit_available = False
        self._ax_available = False
        self._init_frameworks()

    def _init_frameworks(self):
        """Try to import macOS frameworks."""
        try:
            from AppKit import NSWorkspace  # type: ignore
            self._appkit_available = True
            logger.debug("macOS AppKit initialized")
        except ImportError:
            logger.warning("macOS AppKit not available (install pyobjc: pip install pyobjc-framework-Cocoa)")

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
        """Return the frontmost normal window from Quartz (owner, pid, title).

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
                if bounds.get("Width", 0) < 50 or bounds.get("Height", 0) < 50:
                    continue
                return {
                    "owner": w.get("kCGWindowOwnerName"),
                    "pid": w.get("kCGWindowOwnerPID"),
                    "title": w.get("kCGWindowName") or None,
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

    # ── Accessibility ────────────────────────────────────────────────

    def is_a11y_available(self) -> bool:
        return self._ax_available

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
