"""Extended database tests — covers methods missed by the original test_database.py."""
from datetime import datetime

from screenmind.storage.models import ScreenshotEntry, ActivityRecord, DailySummary, DevContext


def test_get_unanalyzed_activities(db):
    """get_unanalyzed_activities returns only unanalyzed entries."""
    for i in range(3):
        entry = ScreenshotEntry(
            timestamp=datetime(2026, 5, 20, 10 + i, 0, 0),
            screenshot_path=f"/tmp/unanalyzed_{i}.jpg",
            analyzed=(i == 1),  # only middle one is analyzed
        )
        db.insert_activity(entry)

    unanalyzed = db.get_unanalyzed_activities(limit=10)
    assert len(unanalyzed) == 2


def test_insert_dev_context(db):
    """insert_dev_context stores git info linked to an activity."""
    entry = ScreenshotEntry(
        timestamp=datetime(2026, 5, 20, 14, 0, 0),
        screenshot_path="/tmp/dev.jpg",
        analyzed=False,
    )
    aid = db.insert_activity(entry)

    ctx = DevContext(
        repo_name="ScreenMind",
        branch="main",
        last_commit="fix: repair tests",
        changed_files=["tests/test_config.py", "tests/test_mcp.py"],
        insertions=27,
        deletions=13,
    )
    db.insert_dev_context(aid, ctx)

    # Retrieve via get_activity_by_id (includes JOIN)
    activity = db.get_activity_by_id(aid)
    assert activity["repo_name"] == "ScreenMind"
    assert activity["branch"] == "main"


def test_get_hourly_heatmap(db):
    """get_hourly_heatmap returns hour-grouped counts."""
    for hour in range(3):
        entry = ScreenshotEntry(
            timestamp=datetime(2026, 5, 20, 10 + hour, 0, 0),
            screenshot_path=f"/tmp/heat_{hour}.jpg",
            analyzed=False,
        )
        aid = db.insert_activity(entry)
        analysis = ActivityRecord(
            app_name="Code", activity_category="coding", activity_summary="test"
        )
        db.update_activity_analysis(aid, analysis)

    heatmap = db.get_hourly_heatmap("2026-05-20", "2026-05-20")
    assert isinstance(heatmap, list)
    assert len(heatmap) == 3
    for row in heatmap:
        assert "hour" in row
        assert "cnt" in row


def test_delete_before(db):
    """delete_before removes entries before a cutoff date."""
    # Insert old and new entries
    for day in [15, 20]:
        entry = ScreenshotEntry(
            timestamp=datetime(2026, 5, day, 10, 0, 0),
            screenshot_path=f"/tmp/old_{day}.jpg",
            analyzed=False,
        )
        db.insert_activity(entry)

    deleted = db.delete_before("2026-05-18")
    assert deleted == 1  # Only the 15th should be deleted

    remaining = db.get_activities_by_date("2026-05-20")
    assert len(remaining) == 1


def test_get_rewind_data(db):
    """get_rewind_data returns analyzed activities ordered chronologically."""
    for hour in range(3):
        entry = ScreenshotEntry(
            timestamp=datetime(2026, 5, 20, 10 + hour, 0, 0),
            screenshot_path=f"/tmp/rewind_{hour}.jpg",
            analyzed=False,
        )
        aid = db.insert_activity(entry)
        analysis = ActivityRecord(
            app_name="Code", activity_category="coding", activity_summary=f"Session {hour}"
        )
        db.update_activity_analysis(aid, analysis)

    data = db.get_rewind_data("2026-05-20")
    assert len(data) == 3
    # Should be in ascending order
    assert data[0]["summary"] == "Session 0"
    assert data[2]["summary"] == "Session 2"


def test_cleanup_old_data_zero_retention(db):
    """cleanup_old_data with retention_days=0 does nothing."""
    result = db.cleanup_old_data(0)
    assert result == {"activities": 0, "meetings": 0}


def test_get_stats_with_categories(db):
    """get_stats returns category breakdown and app counts."""
    categories = ["coding", "coding", "browsing", "communication"]
    apps = ["VS Code", "VS Code", "Chrome", "Slack"]
    for i, (cat, app) in enumerate(zip(categories, apps)):
        entry = ScreenshotEntry(
            timestamp=datetime(2026, 5, 20, 10 + i, 0, 0),
            screenshot_path=f"/tmp/stat2_{i}.jpg",
            analyzed=False,
        )
        aid = db.insert_activity(entry)
        db.update_activity_analysis(aid, ActivityRecord(
            app_name=app, activity_category=cat, activity_summary="test"
        ))

    stats = db.get_stats("2026-05-20", "2026-05-20")
    assert stats["total_activities"] == 4
    assert stats["category_breakdown"]["coding"] == 2
    assert stats["top_apps"]["VS Code"] == 2
    assert stats["meetings_count"] == 0


def test_upsert_summary_with_standup(db):
    """upsert_daily_summary stores summary text."""
    summary = DailySummary(
        date="2026-05-20",
        summary="Productive day",
        total_activities=15,
    )
    db.upsert_daily_summary(summary)

    result = db.get_daily_summary("2026-05-20")
    assert result["summary"] == "Productive day"


def test_get_daily_summary_not_found(db):
    """get_daily_summary returns None for nonexistent dates."""
    result = db.get_daily_summary("2099-01-01")
    assert result is None


# ── active_seconds / tracked_hours ─────────────────────────────────────

from screenmind.storage.database import active_seconds


class TestActiveSeconds:
    def test_empty(self):
        assert active_seconds([], 40) == 0

    def test_single_capture_counts_one_interval(self):
        assert active_seconds(["2026-05-20T10:00:00"], 40) == 40

    def test_short_gaps_counted_fully(self):
        ts = ["2026-05-20T10:00:00", "2026-05-20T10:00:30", "2026-05-20T10:01:00"]
        assert active_seconds(ts, 40) == 40 + 30 + 30

    def test_long_gap_capped(self):
        """A 2-hour lunch break counts as 2 × interval, not 2 hours."""
        ts = ["2026-05-20T12:00:00", "2026-05-20T14:00:00"]
        assert active_seconds(ts, 40) == 40 + 80

    def test_unsorted_input(self):
        ts = ["2026-05-20T10:01:00", "2026-05-20T10:00:00"]
        assert active_seconds(ts, 40) == 40 + 60

    def test_bad_timestamp_counts_one_interval(self):
        ts = ["2026-05-20T10:00:00", "not-a-date", None]
        assert active_seconds(ts, 40) == 40 * 3


def _ok_activity(db, ts, category="coding"):
    activity_id = db.insert_activity(ScreenshotEntry(timestamp=ts, screenshot_path="/tmp/x.jpg"))
    db.update_activity_analysis(activity_id, ActivityRecord(app_name="Code", activity_category=category))
    return activity_id


def test_get_stats_tracked_hours_spans_range(db, monkeypatch):
    """tracked_hours covers every day in the range, not just the first."""
    from screenmind.config import settings
    monkeypatch.setattr(settings, "capture_interval", 40)

    for day in (18, 19, 20):
        for minute in range(0, 60, 1):  # one capture per minute for an hour
            _ok_activity(db, datetime(2026, 5, day, 9, minute, 0))

    one_day = db.get_stats("2026-05-20", "2026-05-20")
    three_days = db.get_stats("2026-05-18", "2026-05-20")

    # 60 captures/day, 1-minute gaps (capped at 80s → 60s each): 40 + 59*60 seconds
    assert one_day["tracked_hours"] == round((40 + 59 * 60) / 3600, 2)
    assert three_days["total_activities"] == 180
    assert three_days["tracked_hours"] > one_day["tracked_hours"] * 2.9


def test_summary_metrics_use_capped_gaps(monkeypatch):
    """Productive hours keep the same gap-capped semantics after the refactor."""
    from screenmind.api.routes.summary import _compute_day_metrics
    from screenmind.config import settings
    monkeypatch.setattr(settings, "capture_interval", 40)

    activities = [
        {"status": "ok", "category": "coding", "timestamp": "2026-05-20T10:00:00"},
        {"status": "ok", "category": "coding", "timestamp": "2026-05-20T10:00:30"},
        {"status": "ok", "category": "browsing", "timestamp": "2026-05-20T10:00:45"},
        {"status": "ok", "category": "coding", "timestamp": "2026-05-20T12:00:00"},
        {"status": "skipped", "category": "coding", "timestamp": "2026-05-20T12:00:10"},
    ]
    metrics = _compute_day_metrics(activities)
    # Productive (coding) only: 40 + 30 + min(7170, 80)
    assert metrics["productive_hours"] == round((40 + 30 + 80) / 3600, 2)
    assert metrics["category_breakdown"] == {"coding": 3, "browsing": 1}
