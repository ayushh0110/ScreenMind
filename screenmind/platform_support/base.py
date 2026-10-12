"""
Abstract Base Class for Platform Adapters
All platform-specific code must implement this interface.
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple


class PlatformAdapter(ABC):
    """
    Abstract interface for platform-specific operations.
    Each OS implements this with its native APIs.
    """

    @abstractmethod
    def get_active_window_title(self) -> Optional[str]:
        """Get the title of the currently focused window."""
        ...

    @abstractmethod
    def get_active_app_name(self) -> Optional[str]:
        """Get the application/process name of the focused window."""
        ...

    @abstractmethod
    def get_foreground_window_handle(self) -> Optional[int]:
        """Get the native window handle of the focused window."""
        ...

    def get_active_window_bounds(self) -> Optional[Tuple[int, int, int, int]]:
        """Focused window as (x, y, width, height), or None if not supported."""
        return None

    @abstractmethod
    def extract_a11y_text(self, hwnd: Optional[int] = None) -> Tuple[Optional[str], str]:
        """
        Extract accessible text from the foreground window.

        Args:
            hwnd: Optional window handle. If None, uses the foreground window.

        Returns:
            Tuple of (text_content, extraction_method)
            - text_content: Extracted text or None
            - extraction_method: "a11y", "none", etc.
        """
        ...

    @abstractmethod
    def is_a11y_available(self) -> bool:
        """Whether accessibility text extraction is available on this platform."""
        ...

    @property
    def platform_name(self) -> str:
        """Human-readable platform name."""
        return "Unknown"

    @property
    def trusts_os_app_name(self) -> bool:
        """Whether get_active_app_name() is a better app identity than the window title.

        False by default: on Windows the process name is an exe like "chrome.exe",
        and titles follow "<content> - <App>". Adapters whose OS reports a clean,
        user-facing app name override this to True.
        """
        return False
