"""Tests for storage/database.py — SQLite operations."""

from datetime import datetime

from screenmind.storage.models import ScreenshotEntry, ActivityRecord, DailySummary


def test_insert_and_get_activity(db):
    entry = ScreenshotEntry(
        timestamp=datetime(2026, 5, 16, 10, 30, 0),
        screenshot_path="/tmp/test.jpg",
        window_title="VS Code",
        detected_app_name="Code",
        bookmarked=False,
        analyzed=False,
    )
    activity_id = db.insert_activity(entry)
    assert activity_id is not None
    assert activity_id > 0

    # Retrieve it
    activity = db.get_activity_by_id(activity_id)
    assert activity is not None
    assert activity["window_title"] == "VS Code"
    assert activity["detected_app"] == "Code"


def test_get_activities_by_date(db):
    for hour in range(3):
        entry = ScreenshotEntry(
            timestamp=datetime(2026, 5, 16, 10 + hour, 0, 0),
            screenshot_path=f"/tmp/test_{hour}.jpg",
            analyzed=False,
        )
        db.insert_activity(entry)

    activities = db.get_activities_by_date("2026-05-16")
    assert len(activities) == 3


def test_get_activities_empty_date(db):
    activities = db.get_activities_by_date("2099-01-01")
    assert activities == []


def test_toggle_bookmark(db):
    entry = ScreenshotEntry(
        timestamp=datetime(2026, 5, 16, 12, 0, 0),
        screenshot_path="/tmp/bm.jpg",
        bookmarked=False,
        analyzed=False,
    )
    aid = db.insert_activity(entry)

    # Toggle on
    new_state = db.toggle_bookmark(aid)
    assert new_state is True

    # Toggle off
    new_state = db.toggle_bookmark(aid)
    assert new_state is False


def test_get_bookmarks(db):
    for i in range(3):
        entry = ScreenshotEntry(
            timestamp=datetime(2026, 5, 16, 10 + i, 0, 0),
            screenshot_path=f"/tmp/bm_{i}.jpg",
            bookmarked=(i == 1),  # Only middle one bookmarked
            analyzed=False,
        )
        db.insert_activity(entry)

    bookmarks = db.get_bookmarks()
    assert len(bookmarks) == 1


def test_update_activity_analysis(db):
    entry = ScreenshotEntry(
        timestamp=datetime(2026, 5, 16, 14, 0, 0),
        screenshot_path="/tmp/analysis.jpg",
        analyzed=False,
    )
    aid = db.insert_activity(entry)

    analysis = ActivityRecord(
        app_name="Chrome",
        activity_category="browsing",
        activity_summary="Reading docs",
        mood="learning",
        confidence=0.85,
    )
    db.update_activity_analysis(aid, analysis)

    activity = db.get_activity_by_id(aid)
    assert activity["app_name"] == "Chrome"
    assert activity["category"] == "browsing"
    assert activity["summary"] == "Reading docs"
    assert activity["analyzed"] == 1


def test_upsert_daily_summary(db):
    summary = DailySummary(
        date="2026-05-16",
        summary="Great day",
        total_activities=10,
    )
    db.upsert_daily_summary(summary)

    result = db.get_daily_summary("2026-05-16")
    assert result is not None
    assert result["summary"] == "Great day"

    # Upsert again (update)
    summary.summary = "Updated summary"
    db.upsert_daily_summary(summary)
    result = db.get_daily_summary("2026-05-16")
    assert result["summary"] == "Updated summary"


def test_summary_and_standup_generation_times_are_separate(db):
    """Each part keeps its own (local) generation time; regenerating one
    leaves the other's text and time alone (#29)."""
    from unittest.mock import patch

    def at(ts):
        mock_dt = patch("screenmind.storage.database.datetime")
        m = mock_dt.start()
        m.now.return_value = datetime.fromisoformat(ts)
        return mock_dt

    p = at("2026-05-16T09:00:00")
    db.upsert_daily_summary(DailySummary(date="2026-05-16", summary="Morning summary"))
    p.stop()
    p = at("2026-05-16T12:00:00")
    returned = db.upsert_daily_summary(DailySummary(date="2026-05-16", summary=""), standup="Standup")
    p.stop()
    assert returned == "2026-05-16T12:00:00"

    row = db.get_daily_summary("2026-05-16")
    assert row["summary"] == "Morning summary"
    assert row["summary_generated_at"] == "2026-05-16T09:00:00"
    assert row["standup_generated_at"] == "2026-05-16T12:00:00"

    p = at("2026-05-16T19:00:00")
    db.upsert_daily_summary(DailySummary(date="2026-05-16", summary="Evening summary"))
    p.stop()
    row = db.get_daily_summary("2026-05-16")
    assert row["summary"] == "Evening summary"
    assert row["summary_generated_at"] == "2026-05-16T19:00:00"
    assert row["standup"] == "Standup"
    assert row["standup_generated_at"] == "2026-05-16T12:00:00"


def test_list_summary_dates(db):
    db.upsert_daily_summary(DailySummary(date="2026-05-14", summary="A"))
    db.upsert_daily_summary(DailySummary(date="2026-05-15", summary=""), standup="S")
    db.upsert_daily_summary(DailySummary(date="2026-05-16", summary="B"), standup="S")
    dates = db.list_summary_dates(limit=2)
    assert dates == [
        {"date": "2026-05-16", "summary": True, "standup": True},
        {"date": "2026-05-15", "summary": False, "standup": True},
    ]


def test_delete_by_date(db):
    for i in range(5):
        entry = ScreenshotEntry(
            timestamp=datetime(2026, 5, 16, 10 + i, 0, 0),
            screenshot_path=f"/tmp/del_{i}.jpg",
            analyzed=False,
        )
        db.insert_activity(entry)

    deleted = db.delete_by_date("2026-05-16")
    assert deleted == 5

    activities = db.get_activities_by_date("2026-05-16")
    assert len(activities) == 0


def test_get_stats(db):
    for i, cat in enumerate(["coding", "coding", "browsing"]):
        entry = ScreenshotEntry(
            timestamp=datetime(2026, 5, 16, 10 + i, 0, 0),
            screenshot_path=f"/tmp/stat_{i}.jpg",
            analyzed=False,
        )
        aid = db.insert_activity(entry)
        analysis = ActivityRecord(
            app_name="App",
            activity_category=cat,
            activity_summary="test",
        )
        db.update_activity_analysis(aid, analysis)

    stats = db.get_stats("2026-05-16", "2026-05-16")
    assert stats["total_activities"] == 3
