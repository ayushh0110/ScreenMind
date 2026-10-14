"""Tests for engine/browsers.py and its use in the analyzer."""

import pytest

from screenmind.engine.browsers import browser_label, is_browser


@pytest.mark.parametrize("name", [
    "msedge", "chrome", "firefox", "brave", "arc",           # Windows / Linux
    "msedge.exe", "Chrome.EXE",                               # with extension
    "Google Chrome", "Microsoft Edge", "Brave Browser",       # macOS app names
    "Safari", "Firefox", "Arc",
])
def test_is_browser(name):
    assert is_browser(name)


@pytest.mark.parametrize("name", ["Code", "Zoom", "Discord", "", None, "chromecast-helper"])
def test_not_browser(name):
    assert not is_browser(name)


@pytest.mark.parametrize("name,label", [
    ("msedge", "Edge"), ("Microsoft Edge", "Edge"),
    ("chrome", "Chrome"), ("Google Chrome", "Chrome"),
    ("Brave Browser", "Brave"), ("Arc", "Arc"),
])
def test_browser_label(name, label):
    assert browser_label(name) == label


def test_analyzer_recognizes_macos_browser_names():
    """macOS reports "Google Chrome", not "chrome" — still a browser window."""
    from screenmind.engine.analyzer import _is_browser_window
    assert _is_browser_window("Pull requests", app_name_hint="Google Chrome")
    assert _is_browser_window("Docs", app_name_hint="Microsoft Edge")
    assert not _is_browser_window("Terminal", app_name_hint="Terminal")
