"""Tests for API endpoints — uses httpx AsyncClient with the FastAPI app."""

import pytest
from datetime import datetime

from screenmind.storage.models import ScreenshotEntry, ActivityRecord
import screenmind.api.dependencies as deps


@pytest.mark.asyncio
async def test_status_endpoint(client):
    resp = await client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "running"


@pytest.mark.asyncio
async def test_timeline_empty(client):
    resp = await client.get("/api/timeline?date=2099-01-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data["activities"] == []


@pytest.mark.asyncio
async def test_timeline_with_data(client, db):
    entry = ScreenshotEntry(
        timestamp=datetime(2026, 5, 16, 10, 0, 0),
        screenshot_path="/tmp/test.jpg",
        window_title="Test Window",
        analyzed=False,
    )
    db.insert_activity(entry)

    resp = await client.get("/api/timeline?date=2026-05-16")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["activities"]) >= 1
    assert any(a["window_title"] == "Test Window" for a in data["activities"])


@pytest.mark.asyncio
async def test_bookmarks_empty(client):
    resp = await client.get("/api/bookmarks")
    assert resp.status_code == 200
    assert resp.json()["bookmarks"] == [] or isinstance(resp.json()["bookmarks"], list)


@pytest.mark.asyncio
async def test_toggle_bookmark(client, db):
    entry = ScreenshotEntry(
        timestamp=datetime(2026, 5, 16, 11, 0, 0),
        screenshot_path="/tmp/bm.jpg",
        bookmarked=False,
        analyzed=False,
    )
    aid = db.insert_activity(entry)

    resp = await client.put(f"/api/activities/{aid}/bookmark")
    assert resp.status_code == 200
    data = resp.json()
    assert data["bookmarked"] is True


@pytest.mark.asyncio
async def test_stats_endpoint(client, db):
    entry = ScreenshotEntry(
        timestamp=datetime(2026, 5, 16, 9, 0, 0),
        screenshot_path="/tmp/s.jpg",
        analyzed=False,
    )
    aid = db.insert_activity(entry)
    db.update_activity_analysis(aid, ActivityRecord(
        app_name="Code", activity_category="coding", activity_summary="test"
    ))

    resp = await client.get("/api/stats?date_from=2026-05-16&date_to=2026-05-16")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_activities" in data


@pytest.mark.asyncio
async def test_settings_get(client):
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "capture_interval" in data
    assert "performance_mode" in data


@pytest.mark.asyncio
async def test_capture_pause_resume(client):
    resp = await client.post("/api/capture/pause")
    assert resp.status_code == 200
    assert resp.json()["paused"] is True

    resp = await client.post("/api/capture/resume")
    assert resp.status_code == 200
    assert resp.json()["paused"] is False


@pytest.mark.asyncio
async def test_rewind_empty(client):
    resp = await client.get("/api/rewind?date=2099-01-01")
    assert resp.status_code == 200
    assert resp.json()["frames"] == []


@pytest.mark.asyncio
async def test_summary_not_generated(client):
    resp = await client.get("/api/summary?date=2099-01-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data["generated"] is False


@pytest.mark.asyncio
async def test_auth_status_no_pin(client):
    resp = await client.get("/api/auth/status")
    assert resp.status_code == 200
    data = resp.json()
    # PIN is cleared in test fixture
    assert data["has_pin"] is False
    assert data["authenticated"] is True


@pytest.mark.asyncio
async def test_activity_not_found(client):
    resp = await client.get("/api/activity/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_clear_timeline(client, db):
    entry = ScreenshotEntry(
        timestamp=datetime(2026, 5, 20, 10, 0, 0),
        screenshot_path="/tmp/clear.jpg",
        analyzed=False,
    )
    db.insert_activity(entry)

    resp = await client.delete("/api/timeline/clear?date=2026-05-20")
    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted"] >= 1


@pytest.mark.asyncio
async def test_meetings_empty(client):
    resp = await client.get("/api/meetings?date=2099-01-01")
    assert resp.status_code == 200
    assert resp.json()["meetings"] == []


@pytest.mark.asyncio
async def test_models_list(client):
    resp = await client.get("/api/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "models" in data
    assert len(data["models"]) >= 1


# ── Summary / standup date validation ─────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["/api/summary/generate", "/api/standup/generate"])
async def test_generate_rejects_future_date(client, endpoint):
    from datetime import date, timedelta
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    resp = await client.post(f"{endpoint}?date={tomorrow}")
    assert resp.status_code == 400
    assert "future" in resp.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["/api/summary/generate", "/api/standup/generate"])
async def test_generate_rejects_malformed_date(client, endpoint):
    resp = await client.post(f"{endpoint}?date=not-a-date")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_generate_accepts_past_date_without_data(client):
    resp = await client.post("/api/summary/generate?date=2020-01-01")
    assert resp.status_code == 200
    assert "No activities" in resp.json()["summary"]["summary"]
