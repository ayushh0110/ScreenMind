"""Tests for the meeting AudioWorker — availability, process checks, meeting detection."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

import screenmind.workers.audio_worker as aw


@pytest.fixture
def worker():
    """An AudioWorker whose startup llama-server check found nothing."""
    with patch("screenmind.engine.llm_client.is_available", return_value=False):
        w = aw.AudioWorker(database=MagicMock())
    return w


@pytest.fixture
def transcription_on(monkeypatch):
    monkeypatch.setattr(aw.settings, "meeting_transcription", True)


# ── Availability recovery ──────────────────────────────────────────────

class TestAvailability:
    def test_disabled_setting_never_checks_server(self, worker, monkeypatch):
        monkeypatch.setattr(aw.settings, "meeting_transcription", False)
        with patch("screenmind.engine.llm_client.is_available") as health:
            assert worker.is_available is False
            health.assert_not_called()

    def test_recovers_when_server_comes_up(self, worker, transcription_on, monkeypatch):
        now = [worker._last_availability_check]
        monkeypatch.setattr(aw.time, "time", lambda: now[0])

        with patch("screenmind.engine.llm_client.is_available", return_value=True) as health:
            # Within the re-check window: no new health request
            now[0] += aw.AVAILABILITY_RECHECK_SECONDS - 1
            assert worker.is_available is False
            health.assert_not_called()

            # After the window: re-checked and recovered
            now[0] += 2
            assert worker.is_available is True
            health.assert_called_once()

    def test_rechecks_at_most_once_per_window(self, worker, transcription_on, monkeypatch):
        now = [worker._last_availability_check + aw.AVAILABILITY_RECHECK_SECONDS]
        monkeypatch.setattr(aw.time, "time", lambda: now[0])

        with patch("screenmind.engine.llm_client.is_available", return_value=False) as health:
            for _ in range(5):
                assert worker.is_available is False
            assert health.call_count == 1

    def test_available_server_not_rechecked(self, transcription_on):
        with patch("screenmind.engine.llm_client.is_available", return_value=True):
            w = aw.AudioWorker(database=MagicMock())
        with patch("screenmind.engine.llm_client.is_available") as health:
            assert w.is_available is True
            health.assert_not_called()


# ── Process-alive check ────────────────────────────────────────────────

def _ps(*names):
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="\n".join(names) + "\n")


class TestMeetingProcessNames:
    @pytest.mark.parametrize("platform,app,expected", [
        ("win32", "Zoom.exe", ["Zoom.exe"]),
        ("darwin", "zoom.us", ["zoom.us"]),
        ("darwin", "Microsoft Teams", ["MSTeams", "Microsoft Teams"]),
        ("linux", "teams-for-linux", ["teams", "teams-for-linux"]),
        ("linux", "chrome", None),
    ])
    def test_lookup(self, monkeypatch, platform, app, expected):
        monkeypatch.setattr(aw.sys, "platform", platform)
        assert aw._meeting_process_names(app) == expected


class TestProcessAlive:
    def test_browser_meeting_assumed_alive(self, worker):
        worker._meeting_process = None
        assert worker._is_meeting_process_alive() is True

    def test_windows_tasklist(self, worker, monkeypatch):
        monkeypatch.setattr(aw.sys, "platform", "win32")
        worker._meeting_process = ["Zoom.exe"]
        out = subprocess.CompletedProcess([], 0, stdout="Zoom.exe   1234 Console  1  200,000 K\n")
        with patch.object(aw.subprocess, "run", return_value=out) as run:
            assert worker._is_meeting_process_alive() is True
            assert run.call_args[0][0][0] == "tasklist"

    def test_windows_not_running(self, worker, monkeypatch):
        monkeypatch.setattr(aw.sys, "platform", "win32")
        worker._meeting_process = ["Zoom.exe"]
        out = subprocess.CompletedProcess([], 0, stdout="INFO: No tasks are running which match the specified criteria.\n")
        with patch.object(aw.subprocess, "run", return_value=out):
            assert worker._is_meeting_process_alive() is False

    def test_macos_app_bundle_path(self, worker, monkeypatch):
        """macOS ps prints full paths for app bundles."""
        monkeypatch.setattr(aw.sys, "platform", "darwin")
        worker._meeting_process = ["zoom.us"]
        out = _ps("/sbin/launchd", "/Applications/zoom.us.app/Contents/MacOS/zoom.us")
        with patch.object(aw.subprocess, "run", return_value=out) as run:
            assert worker._is_meeting_process_alive() is True
            assert run.call_args[0][0] == ["ps", "-A", "-o", "comm="]

    def test_new_teams_on_macos(self, worker, monkeypatch):
        monkeypatch.setattr(aw.sys, "platform", "darwin")
        worker._meeting_process = ["MSTeams", "Microsoft Teams"]
        out = _ps("/Applications/Microsoft Teams.app/Contents/MacOS/MSTeams")
        with patch.object(aw.subprocess, "run", return_value=out):
            assert worker._is_meeting_process_alive() is True

    def test_linux_case_insensitive_exact(self, worker, monkeypatch):
        monkeypatch.setattr(aw.sys, "platform", "linux")
        worker._meeting_process = ["Discord", "discord"]
        with patch.object(aw.subprocess, "run", return_value=_ps("systemd", "Discord")):
            assert worker._is_meeting_process_alive() is True

    def test_no_substring_false_positive(self, worker, monkeypatch):
        """An editor or helper with 'discord' in its name/path is not Discord."""
        monkeypatch.setattr(aw.sys, "platform", "linux")
        worker._meeting_process = ["Discord", "discord"]
        out = _ps("nvim", "discord-rpc-helper", "/home/me/discord-bot/run.sh")
        with patch.object(aw.subprocess, "run", return_value=out):
            assert worker._is_meeting_process_alive() is False

    def test_ps_failure_assumes_alive(self, worker, monkeypatch):
        monkeypatch.setattr(aw.sys, "platform", "linux")
        worker._meeting_process = ["zoom"]
        with patch.object(aw.subprocess, "run", side_effect=FileNotFoundError("ps")):
            assert worker._is_meeting_process_alive() is True
