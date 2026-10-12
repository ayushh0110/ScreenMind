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


@pytest.fixture
def clock(monkeypatch):
    """Controllable time.monotonic() for the front-window cache."""
    import screenmind.platform_support.macos as macos_mod

    state = {"now": 1000.0}
    monkeypatch.setattr(macos_mod.time, "monotonic", lambda: state["now"])

    def advance(seconds):
        state["now"] += seconds

    return advance


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


def test_reflects_changes_between_calls(fake_quartz, adapter, clock):
    """The old NSWorkspace path returned a stale app forever."""
    fake_quartz.windows = [_win("Terminal", "zsh", 7)]
    assert adapter.get_active_app_name() == "Terminal"
    fake_quartz.windows = [_win("Telegram", "Chats", 8)]
    clock(1.5)  # past the snapshot cache
    assert adapter.get_active_app_name() == "Telegram"


def test_snapshot_cached_within_ttl(fake_quartz, adapter, clock):
    """App name, title, PID and bounds in one cycle come from one Quartz call."""
    calls = []
    windows = [_win("Slack", "general", 42)]
    fake_quartz.CGWindowListCopyWindowInfo = lambda opts, wid: calls.append(1) or windows

    adapter.get_active_app_name()
    adapter.get_active_window_title()
    adapter.get_foreground_window_handle()
    adapter.get_active_window_bounds()
    assert len(calls) == 1

    clock(0.5)
    adapter.get_active_app_name()
    assert len(calls) == 1

    clock(0.6)  # 1.1s after the first snapshot
    adapter.get_active_app_name()
    assert len(calls) == 2


def test_no_windows(fake_quartz, adapter):
    fake_quartz.windows = []
    assert adapter.get_active_app_name() is None
    assert adapter.get_active_window_title() is None
    assert adapter.get_foreground_window_handle() is None


def test_window_bounds(fake_quartz, adapter):
    fake_quartz.windows = [
        _win("Rectangle", "", 3, w=10, h=10),
        {**_win("Slack", "general", 42), "kCGWindowBounds": {"X": 100, "Y": 50, "Width": 800, "Height": 600}},
    ]
    assert adapter.get_active_window_bounds() == (100, 50, 800, 600)


def test_window_bounds_none_without_windows(fake_quartz, adapter):
    fake_quartz.windows = []
    assert adapter.get_active_window_bounds() is None


def test_base_adapter_bounds_default_none():
    """Windows/Linux adapters inherit the default and report no bounds."""
    from screenmind.platform_support.base import PlatformAdapter
    assert PlatformAdapter.get_active_window_bounds(object()) is None


def test_screen_capture_window_center_uses_adapter(monkeypatch):
    """ScreenCapture picks the monitor from the adapter's frontmost window."""
    from screenmind.capture.screen import ScreenCapture
    import screenmind.platform_support as ps

    fake = type("A", (), {"get_active_window_bounds": lambda self: (100, 50, 800, 600)})()
    monkeypatch.setattr(ps, "adapter", lambda: fake)
    cap = ScreenCapture.__new__(ScreenCapture)  # skip mss setup
    assert cap._window_center_macos() == (500, 350)

    fake.get_active_window_bounds = lambda: None
    assert cap._window_center_macos() is None
