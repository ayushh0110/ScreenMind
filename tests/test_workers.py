"""Comprehensive tests for capture and analysis workers."""
import pytest
import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

from screenmind.workers.capture_worker import CaptureWorker, CaptureResult


class TestCaptureWorker:
    """Tests for the capture worker."""

    def _make_worker(self):
        queue = asyncio.Queue(maxsize=100)
        return CaptureWorker(queue=queue), queue

    def test_starts_paused(self):
        worker, _ = self._make_worker()
        assert worker.is_paused is True
        assert worker._running is False

    def test_pause_resume(self):
        worker, _ = self._make_worker()
        worker.resume(source="test")
        assert worker.is_paused is False
        worker.pause(source="test")
        assert worker.is_paused is True

    def test_stats_keys(self):
        worker, _ = self._make_worker()
        stats = worker.stats
        assert "running" in stats
        assert "paused" in stats
        assert "captures" in stats
        assert "skipped" in stats

    def test_trigger_bookmark(self):
        worker, _ = self._make_worker()
        assert worker._pending_bookmark is False
        worker.trigger_bookmark()
        assert worker._pending_bookmark is True

    def test_stop_sets_running_false(self):
        worker, _ = self._make_worker()
        worker._running = True
        worker.stop()
        assert worker._running is False

    def test_pause_resets_dedup(self):
        """Pausing resets the dedup hash so next capture is always fresh."""
        worker, _ = self._make_worker()
        worker._paused = False  # Must be unpaused for pause() to run (idempotent guard)
        worker._dedup._last_hash = "something"
        worker.pause(source="test")
        assert worker._dedup._last_hash is None

    def test_initial_counts_zero(self):
        worker, _ = self._make_worker()
        assert worker._capture_count == 0
        assert worker._skip_count == 0
        assert worker._consecutive_skips == 0


class TestCaptureResult:
    """Tests for CaptureResult dataclass."""

    def test_create_basic(self, tmp_path):
        result = CaptureResult(
            filepath=tmp_path / "test.jpg",
            timestamp=datetime.now(),
            window_title="Test Window",
            app_name="TestApp",
        )
        assert result.app_name == "TestApp"
        assert result.bookmarked is False
        assert result.activity_id is None
        assert result.a11y_text is None
        assert result.phash is None

    def test_create_bookmarked(self, tmp_path):
        result = CaptureResult(
            filepath=tmp_path / "test.jpg",
            timestamp=datetime.now(),
            bookmarked=True,
        )
        assert result.bookmarked is True


class TestAnalysisWorkerStats:
    """Tests for analysis worker state management."""

    def test_flush_queue(self):
        """flush_queue drains all items."""
        from screenmind.workers.analysis_worker import AnalysisWorker

        queue = asyncio.Queue(maxsize=100)
        db = MagicMock()
        worker = AnalysisWorker(queue=queue, database=db)

        # Add some items
        for i in range(5):
            queue.put_nowait(MagicMock())

        assert queue.qsize() == 5
        worker.flush_queue()
        assert queue.qsize() == 0

    def test_stats_keys(self):
        from screenmind.workers.analysis_worker import AnalysisWorker

        queue = asyncio.Queue(maxsize=100)
        db = MagicMock()
        worker = AnalysisWorker(queue=queue, database=db)

        stats = worker.stats
        assert "running" in stats
        assert "processed" in stats
        assert "errors" in stats
        assert "queue_size" in stats
        assert "cache_hits" in stats
        assert "cache_size" in stats

    def test_initial_state(self):
        from screenmind.workers.analysis_worker import AnalysisWorker

        queue = asyncio.Queue(maxsize=100)
        db = MagicMock()
        worker = AnalysisWorker(queue=queue, database=db)

        assert worker._processed == 0
        assert worker._errors == 0
        assert worker._cache_hits == 0
        assert len(worker._app_cache) == 0
        assert len(worker._priority_items) == 0

    def test_stop(self):
        from screenmind.workers.analysis_worker import AnalysisWorker

        queue = asyncio.Queue(maxsize=100)
        db = MagicMock()
        worker = AnalysisWorker(queue=queue, database=db)
        worker._running = True
        worker.stop()
        assert worker._running is False


class TestURLExtraction:
    """Tests for URL extraction in analysis worker."""

    def test_extract_url_basic(self):
        from screenmind.workers.analysis_worker import _extract_url
        assert _extract_url("Visit https://github.com/user/repo today") == "https://github.com/user/repo"

    def test_extract_url_none_for_empty(self):
        from screenmind.workers.analysis_worker import _extract_url
        assert _extract_url("") is None
        assert _extract_url("no urls here") is None

    def test_extract_url_filters_noise(self):
        from screenmind.workers.analysis_worker import _extract_url
        # localhost and CDN URLs should be filtered
        assert _extract_url("http://localhost:3000/api") is None
        assert _extract_url("https://cdn.example.com/file.js") is None

    def test_extract_all_urls(self):
        from screenmind.workers.analysis_worker import _extract_all_urls
        text = "Check https://github.com and https://dev.to for updates"
        urls = _extract_all_urls(text)
        assert len(urls) == 2
        assert "https://github.com" in urls[0]

    def test_extract_url_strips_punctuation(self):
        from screenmind.workers.analysis_worker import _extract_all_urls
        urls = _extract_all_urls("See https://example.com/page.")
        assert urls[0] == "https://example.com/page"


class TestAnalysisWorkerBackfill:
    """Backfill re-analyzes rows that were never analyzed."""

    async def test_backfill_passes_detected_app_as_hint(self, db, tmp_path):
        """Unanalyzed rows have app_name NULL; the OS-detected app must be used."""
        from PIL import Image
        from screenmind.storage.models import ScreenshotEntry
        from screenmind.workers.analysis_worker import AnalysisWorker

        shot = tmp_path / "shot.jpg"
        Image.new("RGB", (64, 64), "white").save(shot)
        db.insert_activity(ScreenshotEntry(
            timestamp=datetime.now(),
            screenshot_path=str(shot),
            window_title="Chats",
            detected_app_name="Telegram",
            bookmarked=False,
            analyzed=False,
        ))

        worker = AnalysisWorker(queue=asyncio.Queue(maxsize=100), database=db)
        worker._process = AsyncMock()
        await worker._backfill_skipped()

        worker._process.assert_awaited_once()
        capture = worker._process.await_args.args[0]
        assert capture.app_name == "Telegram"
        assert capture.window_title == "Chats"

    async def test_backfill_ignores_unknown_app_name(self, db, tmp_path):
        """A skipped row with no OS detection stores app_name="unknown".

        That placeholder must not reach the analyzer as an OS hint, or
        _normalize() would record "unknown" as the app name.
        """
        from PIL import Image
        from screenmind.storage.models import ActivityRecord, ScreenshotEntry
        from screenmind.workers.analysis_worker import AnalysisWorker

        shot = tmp_path / "shot.jpg"
        Image.new("RGB", (64, 64), "white").save(shot)
        activity_id = db.insert_activity(ScreenshotEntry(
            timestamp=datetime.now(),
            screenshot_path=str(shot),
            window_title="Untitled",
            detected_app_name=None,
            bookmarked=False,
            analyzed=False,
        ))
        db.update_activity_analysis(
            activity_id=activity_id,
            analysis=ActivityRecord(app_name="unknown", activity_summary="Skipped (analysis backlog)"),
            analysis_method="skipped",
            status="skipped",
        )

        worker = AnalysisWorker(queue=asyncio.Queue(maxsize=100), database=db)
        worker._process = AsyncMock()
        await worker._backfill_skipped()

        capture = worker._process.await_args.args[0]
        assert capture.app_name is None


class TestCaptureWorkerIncognito:
    """Incognito promises that nothing is recorded."""

    @pytest.fixture
    def worker(self):
        # pause()/resume() persist to settings.json — keep tests off the real file
        with patch("screenmind.config.Settings.save_runtime_overrides"):
            w = CaptureWorker(queue=asyncio.Queue(maxsize=100))
            w._audio_worker = MagicMock()
            yield w

    def test_incognito_pauses_and_suspends_meetings(self, worker):
        worker.resume(source="test")
        worker.set_incognito(True)
        assert worker.incognito is True
        assert worker.is_paused is True
        worker._audio_worker.set_suspended.assert_called_with(True)

    def test_bookmark_refused_while_incognito(self, worker):
        """Hotkey, dashboard, MCP and agents all go through trigger_bookmark()."""
        worker.set_incognito(True)
        assert worker.trigger_bookmark() is False
        assert worker._pending_bookmark is False

    def test_turning_incognito_on_drops_queued_bookmark(self, worker):
        assert worker.trigger_bookmark() is True
        worker.set_incognito(True)
        assert worker._pending_bookmark is False

    def test_incognito_off_resumes(self, worker):
        worker.set_incognito(True)
        worker.set_incognito(False)
        assert worker.incognito is False
        assert worker.is_paused is False
        worker._audio_worker.set_suspended.assert_called_with(False)

    def test_resume_ends_incognito(self, worker):
        """Start Capturing / pause hotkey while incognito turns incognito off."""
        worker.set_incognito(True)
        worker.resume(source="dashboard")
        assert worker.incognito is False
        worker._audio_worker.set_suspended.assert_called_with(False)

    async def test_meeting_detection_skipped_while_incognito(self, worker):
        worker.set_incognito(True)
        worker._running = True

        async def stop_after_one_tick(_):
            worker._running = False

        with patch("screenmind.workers.capture_worker.get_active_app_name", return_value="Zoom"), \
             patch("screenmind.workers.capture_worker.asyncio.sleep", side_effect=stop_after_one_tick):
            await worker.run()
        worker._audio_worker.check_meeting.assert_not_called()

    async def test_title_only_fetched_for_browsers(self, worker):
        worker._running = True

        async def stop_after_one_tick(_):
            worker._running = False

        with patch("screenmind.workers.capture_worker.get_active_app_name", return_value="Zoom"), \
             patch("screenmind.workers.capture_worker.get_active_window_title") as title, \
             patch("screenmind.workers.capture_worker.asyncio.sleep", side_effect=stop_after_one_tick):
            await worker.run()
        title.assert_not_called()
        worker._audio_worker.check_meeting.assert_called_once_with("Zoom", None)
