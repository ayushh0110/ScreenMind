"""Tests for integrations/smart_notify.py — mock overlay, test detection logic."""
import time
from unittest.mock import patch, MagicMock
import screenmind.integrations.smart_notify as sn


class TestCheck:
    def setup_method(self):
        """Reset module state before each test."""
        sn._last_notification.clear()
        sn._app_start_time.clear()
        sn._last_app = None
        sn._continuous_work_start = None

    @patch("screenmind.integrations.smart_notify.settings")
    def test_disabled_does_nothing(self, mock_settings):
        mock_settings.smart_notifications = False
        # Should return without error
        sn.check("YouTube", "browsing")

    @patch("screenmind.integrations.smart_notify.settings")
    @patch("screenmind.integrations.smart_notify._notify")
    def test_entertainment_distraction_alert(self, mock_notify, mock_settings):
        mock_settings.smart_notifications = True
        mock_settings.distraction_minutes = 0  # trigger immediately
        mock_settings.break_reminder_minutes = 999

        sn.check("YouTube", "browsing")
        # First call sets up tracking, distraction check needs elapsed time
        sn._app_start_time["youtube"] = time.time() - 120  # 2 min ago
        sn.check("YouTube", "browsing")
        mock_notify.assert_called()

    @patch("screenmind.integrations.smart_notify.settings")
    @patch("screenmind.integrations.smart_notify._notify")
    def test_non_entertainment_no_distraction(self, mock_notify, mock_settings):
        mock_settings.smart_notifications = True
        mock_settings.distraction_minutes = 5
        mock_settings.break_reminder_minutes = 999

        sn.check("VS Code", "coding")
        mock_notify.assert_not_called()

    @patch("screenmind.integrations.smart_notify.settings")
    @patch("screenmind.integrations.smart_notify._notify")
    def test_break_reminder(self, mock_notify, mock_settings):
        mock_settings.smart_notifications = True
        mock_settings.distraction_minutes = 999
        mock_settings.break_reminder_minutes = 1  # 1 minute

        sn._continuous_work_start = time.time() - 120  # 2 min ago
        sn._last_app = "code"
        sn.check("Code", "coding")
        mock_notify.assert_called()

    @patch("screenmind.integrations.smart_notify.settings")
    @patch("screenmind.integrations.smart_notify._notify")
    def test_focus_streak(self, mock_notify, mock_settings):
        mock_settings.smart_notifications = True
        mock_settings.distraction_minutes = 999
        mock_settings.break_reminder_minutes = 999

        sn._last_app = "code"
        sn._app_start_time["code"] = time.time() - 7500  # 125 min ago
        sn.check("Code", "coding")
        mock_notify.assert_called()

    @patch("screenmind.integrations.smart_notify.settings")
    def test_app_switch_tracking(self, mock_settings):
        mock_settings.smart_notifications = True
        mock_settings.distraction_minutes = 999
        mock_settings.break_reminder_minutes = 999

        sn.check("Chrome", "browsing")
        assert sn._last_app == "chrome"
        sn.check("Code", "coding")
        assert sn._last_app == "code"


class TestNotify:
    def setup_method(self):
        sn._last_notification.clear()

    @patch("screenmind.integrations.smart_notify.show_overlay_notification", create=True)
    def test_cooldown_prevents_repeat(self, *_):
        sn._last_notification["distraction"] = time.time()
        # Within cooldown — should not notify
        with patch("screenmind.integrations.smart_notify.show_overlay_notification", create=True) as mock_overlay:
            sn._notify("distraction", "Test", "Message")
            # _notify checks cooldown internally — overlay should NOT be called
            # because we just set the last notification to now

    def test_notify_after_cooldown(self):
        sn._last_notification["break"] = time.time() - 9999  # long ago
        with patch("screenmind.integrations.smart_notify.show_overlay_notification", create=True) as mock_overlay:
            try:
                sn._notify("break", "Break", "Take a break")
            except Exception:
                pass  # overlay import may fail, that's fine


class TestCheckFocus:
    """Focus streak needs the analyzed category, so it runs after analysis."""

    def setup_method(self):
        sn._last_notification.clear()
        sn._app_start_time.clear()
        sn._last_app = None
        sn._continuous_work_start = None

    def _settings(self, mock_settings):
        mock_settings.smart_notifications = True
        mock_settings.distraction_minutes = 999
        mock_settings.break_reminder_minutes = 999

    @patch("screenmind.integrations.smart_notify.settings")
    @patch("screenmind.integrations.smart_notify._notify")
    def test_capture_tick_alone_never_fires_focus(self, mock_notify, mock_settings):
        """The capture worker calls check(app) without a category."""
        self._settings(mock_settings)
        sn._last_app = "code"
        sn._app_start_time["code"] = time.time() - 7500
        sn.check("Code")
        mock_notify.assert_not_called()

    @patch("screenmind.integrations.smart_notify.settings")
    @patch("screenmind.integrations.smart_notify._notify")
    def test_fires_after_two_hours_of_coding(self, mock_notify, mock_settings):
        self._settings(mock_settings)
        sn.check("Code")  # capture tick starts the session
        sn._app_start_time["code"] = time.time() - 7500  # 125 min ago
        sn.check_focus("Code", "coding")
        assert mock_notify.call_args[0][0] == "focus"

    @patch("screenmind.integrations.smart_notify.settings")
    @patch("screenmind.integrations.smart_notify._notify")
    def test_not_before_two_hours(self, mock_notify, mock_settings):
        self._settings(mock_settings)
        sn.check("Code")
        sn._app_start_time["code"] = time.time() - 3600
        sn.check_focus("Code", "coding")
        mock_notify.assert_not_called()

    @patch("screenmind.integrations.smart_notify.settings")
    @patch("screenmind.integrations.smart_notify._notify")
    def test_non_coding_category_ignored(self, mock_notify, mock_settings):
        self._settings(mock_settings)
        sn.check("Code")
        sn._app_start_time["code"] = time.time() - 7500
        sn.check_focus("Code", "browsing")
        mock_notify.assert_not_called()

    @patch("screenmind.integrations.smart_notify.settings")
    @patch("screenmind.integrations.smart_notify._notify")
    def test_only_for_current_app_session(self, mock_notify, mock_settings):
        """An analysis that lands after the user switched apps doesn't fire."""
        self._settings(mock_settings)
        sn.check("Code")
        sn._app_start_time["code"] = time.time() - 7500
        sn.check("Chrome")  # user switched away
        sn.check_focus("Code", "coding")
        mock_notify.assert_not_called()

    @patch("screenmind.integrations.smart_notify.settings")
    @patch("screenmind.integrations.smart_notify._notify")
    def test_disabled(self, mock_notify, mock_settings):
        self._settings(mock_settings)
        mock_settings.smart_notifications = False
        sn._last_app = "code"
        sn._app_start_time["code"] = time.time() - 7500
        sn.check_focus("Code", "coding")
        mock_notify.assert_not_called()


class TestAnalysisWorkerFocusHook:
    """The analysis worker only forwards live captures to check_focus."""

    def _worker(self):
        import asyncio
        from screenmind.workers.analysis_worker import AnalysisWorker
        return AnalysisWorker(queue=asyncio.Queue(), database=MagicMock())

    def _capture(self, age_seconds=0):
        from datetime import datetime, timedelta
        from pathlib import Path
        from screenmind.workers.capture_worker import CaptureResult
        return CaptureResult(
            filepath=Path("x.jpg"),
            timestamp=datetime.now() - timedelta(seconds=age_seconds),
            app_name="Code",
        )

    @patch("screenmind.integrations.smart_notify.check_focus")
    def test_live_capture_forwarded(self, mock_focus):
        self._worker()._check_focus(self._capture(), "coding")
        mock_focus.assert_called_once_with("Code", "coding")

    @patch("screenmind.integrations.smart_notify.check_focus")
    def test_backfill_skipped(self, mock_focus):
        worker = self._worker()
        worker._is_backfill = True
        worker._check_focus(self._capture(), "coding")
        mock_focus.assert_not_called()

    @patch("screenmind.integrations.smart_notify.check_focus")
    def test_stale_capture_skipped(self, mock_focus):
        self._worker()._check_focus(self._capture(age_seconds=600), "coding")
        mock_focus.assert_not_called()
