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


# ── Meeting detection (native apps + browser tabs) ─────────────────────

@pytest.fixture
def default_meeting_apps(monkeypatch):
    monkeypatch.setattr(aw.settings, "meeting_apps", "zoom,teams,meet,webex,slack,discord")


@pytest.mark.usefixtures("default_meeting_apps")
class TestDetectMeeting:
    @pytest.mark.parametrize("app,title,label", [
        # Google Meet in Edge — Edge's zero-width space and "and N more pages" suffix
        ("msedge", "Meet - abc-defg-hij and 2 more pages - Personal - Microsoft​ Edge",
         "Google Meet (Edge)"),
        ("msedge", "Meet – abc-defg-hij - Microsoft​ Edge", "Google Meet (Edge)"),
        ("chrome", "Meet - abc-defg-hij - Google Chrome", "Google Meet (Chrome)"),
        ("chrome", "Google Meet - Google Chrome", "Google Meet (Chrome)"),
        ("firefox", "meet.google.com/abc-defg-hij — Mozilla Firefox", "Google Meet (Firefox)"),
        # Other services on the web
        ("msedge", "Meeting with Priya | Microsoft Teams - Microsoft​ Edge", "Microsoft Teams (Edge)"),
        ("chrome", "Zoom Meeting - Google Chrome", "Zoom (Chrome)"),
        ("brave", "Cisco Webex Meetings - Brave", "Webex (Brave)"),
        # macOS app names
        ("Google Chrome", "Meet - abc-defg-hij", "Google Meet (Chrome)"),
        ("Microsoft Edge", "Meet - abc-defg-hij", "Google Meet (Edge)"),
        ("Arc", "Meet - abc-defg-hij", "Google Meet (Arc)"),
        ("Firefox", "Meet - abc-defg-hij", "Google Meet (Firefox)"),
    ])
    def test_browser_meetings(self, app, title, label):
        assert aw._detect_meeting(app, title) == (label, True)

    @pytest.mark.parametrize("app,title", [
        ("chrome", "Meeting notes.docx - Google Docs - Google Chrome"),
        ("msedge", "Meet the team - Google Docs - Microsoft​ Edge"),
        ("chrome", "How to zoom in on photos - Google Search - Google Chrome"),
        ("firefox", "Inbox (3) - Gmail — Mozilla Firefox"),
        ("chrome", None),
    ])
    def test_ordinary_browser_tabs_ignored(self, app, title):
        assert aw._detect_meeting(app, title) is None

    def test_native_apps_unchanged(self):
        assert aw._detect_meeting("Zoom", "Zoom Meeting") == ("Zoom", False)
        assert aw._detect_meeting("ms-teams", None) == ("ms-teams", False)
        assert aw._detect_meeting("Code", "Meet - abc - Visual Studio Code") is None

    def test_keyword_removed_disables_browser_pattern(self, monkeypatch):
        monkeypatch.setattr(aw.settings, "meeting_apps", "zoom,teams")
        assert aw._detect_meeting("chrome", "Meet - abc-defg-hij - Google Chrome") is None
        assert aw._detect_meeting("chrome", "Zoom Meeting - Google Chrome") == ("Zoom (Chrome)", True)


@pytest.mark.usefixtures("default_meeting_apps", "transcription_on")
class TestCheckMeeting:
    @pytest.fixture
    def live_worker(self, worker):
        worker._available = True
        worker._start_audio_probe = MagicMock()
        return worker

    def test_meet_in_edge_starts_probe(self, live_worker):
        live_worker.check_meeting("msedge", "Meet - abc-defg-hij - Microsoft​ Edge")
        live_worker._start_audio_probe.assert_called_once()
        assert live_worker._pending_meeting_app == "Google Meet (Edge)"
        assert live_worker._pending_in_browser is True

    def test_process_name_only_still_works(self, live_worker):
        """Older callers pass only the app name."""
        live_worker.check_meeting("Zoom")
        live_worker._start_audio_probe.assert_called_once()
        assert live_worker._pending_in_browser is False

    def test_plain_browser_tab_no_probe(self, live_worker):
        live_worker.check_meeting("msedge", "GitHub - Microsoft​ Edge")
        live_worker._start_audio_probe.assert_not_called()


class TestStartMeetingProcess:
    @pytest.fixture
    def started(self, worker, monkeypatch):
        worker._recording_loop = lambda: None
        monkeypatch.setattr("screenmind.engine.model_manager.is_audio_capable", lambda: True)
        monkeypatch.setattr("screenmind.ui.overlay.show_overlay_notification", lambda *a, **k: None)
        yield worker
        worker._stop_recording.set()

    def test_browser_meeting_has_no_process(self, started, monkeypatch):
        """A "Microsoft Teams (Edge)" label must not map to ms-teams.exe."""
        monkeypatch.setattr(aw.sys, "platform", "win32")
        started._start_meeting("Microsoft Teams (Edge)", in_browser=True)
        assert started._meeting_process is None
        started._db.insert_meeting.assert_called_once()
        assert started._db.insert_meeting.call_args.kwargs["app_name"] == "Microsoft Teams (Edge)"

    def test_native_meeting_maps_process(self, started, monkeypatch):
        monkeypatch.setattr(aw.sys, "platform", "win32")
        started._start_meeting("Zoom")
        assert started._meeting_process == ["Zoom.exe"]
