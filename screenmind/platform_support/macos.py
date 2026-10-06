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

    def get_foreground_window_handle(self) -> Optional[int]:
        """macOS doesn't use integer window handles like Win32. Returns PID instead."""
        try:
            if self._appkit_available:
                from AppKit import NSWorkspace  # type: ignore
                active = NSWorkspace.sharedWorkspace().frontmostApplication()
                return active.processIdentifier() if active else None
        except Exception:
            pass
        return None

    def get_active_window_title(self) -> Optional[str]:
        """Get active window title using AppKit or osascript fallback."""
        # Method 1: AppKit
        if self._appkit_available:
            try:
                from AppKit import NSWorkspace  # type: ignore
                active = NSWorkspace.sharedWorkspace().frontmostApplication()
                if active:
                    return active.localizedName()
            except Exception:
                pass

        # Method 2: osascript fallback
        try:
            result = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to get name of first application process whose frontmost is true'],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass

        return None

    def get_active_app_name(self) -> Optional[str]:
        """Get active app name. On macOS, same as window title source."""
        if self._appkit_available:
            try:
                from AppKit import NSWorkspace  # type: ignore
                active = NSWorkspace.sharedWorkspace().frontmostApplication()
                if active:
                    return active.localizedName()
            except Exception:
                pass

        # Fallback
        title = self.get_active_window_title()
        if title:
            parts = title.rsplit(" - ", 1)
            return parts[-1] if parts else title
        return None

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
