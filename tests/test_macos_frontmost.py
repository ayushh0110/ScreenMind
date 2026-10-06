"""
Tests for macOS frontmost-window detection via Quartz.

Quartz is faked through sys.modules, so these run on any OS (CI is Windows).
"""

import sys
import types

import pytest

from screenmind.platform_support.macos import MacOSAdapter


def _win(owner, title, pid, layer=0, w=800, h=600):
    return {
        "kCGWindowOwnerName": owner,
        "kCGWindowName": title,
        "kCGWindowOwnerPID": pid,
        "kCGWindowLayer": layer,
        "kCGWindowBounds": {"X": 0, "Y": 0, "Width": w, "Height": h},
    }


@pytest.fixture
def fake_quartz(monkeypatch):
    """Install a fake Quartz module; tests set `.windows` (front to back)."""
    mod = types.ModuleType("Quartz")
    mod.kCGWindowListOptionOnScreenOnly = 1
    mod.kCGWindowListExcludeDesktopElements = 16
    mod.kCGNullWindowID = 0
    mod.windows = []
    mod.CGWindowListCopyWindowInfo = lambda opts, wid: mod.windows
    monkeypatch.setitem(sys.modules, "Quartz", mod)
    return mod


@pytest.fixture
def adapter():
    return MacOSAdapter()


def test_first_normal_window_wins(fake_quartz, adapter):
    fake_quartz.windows = [
        _win("Window Server", "Menubar", 1, layer=25),   # menu bar, skipped
        _win("Slack", "general - Acme - Slack", 42),
        _win("Terminal", "zsh — 120×30", 7),
    ]
    assert adapter.get_active_app_name() == "Slack"
    assert adapter.get_active_window_title() == "general - Acme - Slack"
    assert adapter.get_foreground_window_handle() == 42


def test_tiny_windows_skipped(fake_quartz, adapter):
    fake_quartz.windows = [
        _win("Rectangle", "", 3, w=10, h=10),            # overlay helper
        _win("Google Chrome", "Pull requests", 9),
    ]
    assert adapter.get_active_app_name() == "Google Chrome"


def test_title_falls_back_to_owner(fake_quartz, adapter):
    """kCGWindowName is empty without Screen Recording permission."""
    fake_quartz.windows = [_win("Finder", None, 5)]
    assert adapter.get_active_window_title() == "Finder"


def test_reflects_changes_between_calls(fake_quartz, adapter):
    """The old NSWorkspace path returned a stale app forever."""
    fake_quartz.windows = [_win("Terminal", "zsh", 7)]
    assert adapter.get_active_app_name() == "Terminal"
    fake_quartz.windows = [_win("Telegram", "Chats", 8)]
    assert adapter.get_active_app_name() == "Telegram"


def test_no_windows(fake_quartz, adapter):
    fake_quartz.windows = []
    assert adapter.get_active_app_name() is None
    assert adapter.get_active_window_title() is None
    assert adapter.get_foreground_window_handle() is None
