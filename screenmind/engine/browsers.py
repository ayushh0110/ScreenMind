"""
Browser identification shared by the analyzer and meeting detection.

The OS reports browsers differently per platform:
  - Windows / Linux X11: process name ("msedge", "chrome", "firefox")
  - Linux Wayland: compositor app ID / window class ("google-chrome")
  - macOS: window owner / app name ("Microsoft Edge", "Google Chrome")
"""

from typing import Optional

# Windows process names (without .exe) and Linux X11 /proc/<pid>/comm values.
# Linux truncates comm to 15 chars: "chromium-browser" → "chromium-browse".
_PROCESS_NAMES = {
    "chrome", "chromium", "chromium-browse", "firefox", "firefox-esr",
    "brave", "opera", "safari", "vivaldi", "arc",
    "msedge",
}

# Linux Wayland app IDs (sway/niri app_id, Hyprland class), incl. Flatpak IDs
_WAYLAND_APP_IDS = {
    "google-chrome", "google-chrome-stable", "chromium-browser",
    "microsoft-edge", "microsoft-edge-stable", "brave-browser",
    "com.google.chrome", "org.chromium.chromium", "com.microsoft.edge",
    "com.brave.browser", "org.mozilla.firefox",
}

# macOS app names (as reported by the window owner)
_MACOS_APP_NAMES = {
    "google chrome", "microsoft edge", "brave browser",
    "safari", "firefox", "arc",
}

BROWSER_NAMES = frozenset(_PROCESS_NAMES | _WAYLAND_APP_IDS | _MACOS_APP_NAMES)

_LABELS = {
    "chrome": "Chrome", "google chrome": "Chrome", "google-chrome": "Chrome",
    "google-chrome-stable": "Chrome", "com.google.chrome": "Chrome",
    "msedge": "Edge", "microsoft edge": "Edge", "microsoft-edge": "Edge",
    "microsoft-edge-stable": "Edge", "com.microsoft.edge": "Edge",
    "firefox": "Firefox", "firefox-esr": "Firefox", "org.mozilla.firefox": "Firefox",
    "brave": "Brave", "brave browser": "Brave", "brave-browser": "Brave",
    "com.brave.browser": "Brave",
    "chromium": "Chromium", "chromium-browser": "Chromium",
    "chromium-browse": "Chromium", "org.chromium.chromium": "Chromium",
    "safari": "Safari", "arc": "Arc", "opera": "Opera", "vivaldi": "Vivaldi",
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
