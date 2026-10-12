"""
Browser identification shared by the analyzer and meeting detection.

The OS reports browsers differently per platform:
  - Windows / Linux: process name ("msedge", "chrome", "firefox")
  - macOS: window owner / app name ("Microsoft Edge", "Google Chrome")
"""

from typing import Optional

# Windows / Linux process names
_PROCESS_NAMES = {
    "chrome", "chromium", "firefox", "firefox-esr",
    "brave", "opera", "safari", "vivaldi", "arc",
    "msedge",
}

# macOS app names (as reported by the window owner)
_MACOS_APP_NAMES = {
    "google chrome", "microsoft edge", "brave browser",
    "safari", "firefox", "arc",
}

BROWSER_NAMES = frozenset(_PROCESS_NAMES | _MACOS_APP_NAMES)

_LABELS = {
    "chrome": "Chrome", "google chrome": "Chrome",
    "msedge": "Edge", "microsoft edge": "Edge",
    "firefox": "Firefox", "firefox-esr": "Firefox",
    "brave": "Brave", "brave browser": "Brave",
    "safari": "Safari", "arc": "Arc", "opera": "Opera",
    "vivaldi": "Vivaldi", "chromium": "Chromium",
}


def _normalize(app_name: Optional[str]) -> str:
    name = (app_name or "").strip().lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name


def is_browser(app_name: Optional[str]) -> bool:
    """True if the OS-reported app/process name is a web browser."""
    return _normalize(app_name) in BROWSER_NAMES


def browser_label(app_name: Optional[str]) -> str:
    """Short display name, e.g. "msedge" → "Edge", "Google Chrome" → "Chrome"."""
    name = _normalize(app_name)
    return _LABELS.get(name, (app_name or "Browser").strip())
