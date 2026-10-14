"""Tests for voice memo storage, re-transcription, and the re-analyze endpoint."""

import json
from datetime import datetime
from unittest.mock import patch

import pytest
from PIL import Image

import screenmind.api.dependencies as deps
from screenmind.engine import voice_memo
from screenmind.storage import files
from screenmind.storage.models import ActivityRecord, ScreenshotEntry


@pytest.fixture
def memos_dir(tmp_path, monkeypatch):
    d = tmp_path / "memos"
    (d / "2026-10-13").mkdir(parents=True)
    monkeypatch.setattr(files, "memos_dir", lambda: d)
    return d


@pytest.fixture
def wav_file(memos_dir):
    path = memos_dir / "2026-10-13" / "memo_10-00-00.wav"
    path.write_bytes(b"RIFF....WAVEfake")
    return path


def _memo_row(db, wav_path, summary="old summary"):
    activity_id = db.insert_activity(ScreenshotEntry(
        timestamp=datetime.now(),
        screenshot_path="",
        window_title="Voice Memo",
        detected_app_name="Voice Memo",
        bookmarked=True,
    ))
    db.update_activity_analysis(activity_id, ActivityRecord(
        app_name="Voice Memo", activity_summary=summary, detailed_context=str(wav_path),
    ))
    return activity_id


# ── memo_wav_path ──────────────────────────────────────────────────────

class TestMemoWavPath:
    def test_wav_inside_memos_dir(self, wav_file):
        assert files.memo_wav_path(str(wav_file)) == wav_file.resolve()

    def test_missing_file_still_recognized(self, memos_dir):
        """A deleted WAV is still a memo path — callers report it as missing."""
        path = memos_dir / "2026-10-13" / "gone.wav"
        assert files.memo_wav_path(str(path)) == path.resolve()

    def test_wav_outside_memos_dir(self, tmp_path, memos_dir):
        assert files.memo_wav_path(str(tmp_path / "elsewhere.wav")) is None

    def test_traversal_out_of_memos_dir(self, memos_dir):
        sneaky = memos_dir / ".." / "secret.wav"
        assert files.memo_wav_path(str(sneaky)) is None

    @pytest.mark.parametrize("details", [
        None, "", "Editing auth_middleware.py in VS Code. The user is reviewing a PR.",
        "notes.txt",
    ])
    def test_screenshot_details(self, details, memos_dir):
        assert files.memo_wav_path(details) is None


# ── save_voice_memo / retranscribe_memo ────────────────────────────────

class TestSaveVoiceMemo:
    def test_saves_full_transcript(self, db, wav_file):
        transcript = "Remember to " + "review the PR " * 30
        with patch.object(voice_memo.llm_client, "transcribe_audio", return_value=transcript):
            result = voice_memo.save_voice_memo(db, b"wav", None, wav_file)

        assert result["status"] == "ok"
        row = db.get_activity_by_id(result["activity_id"])
        assert row["summary"] == transcript.strip()[:200]
        assert row["ocr_text"] == transcript.strip()
        assert row["details"] == str(wav_file)
        assert row["bookmarked"]
        assert row["status"] == "ok"

    def test_empty_transcript_saves_fallback(self, db, wav_file):
        with patch.object(voice_memo.llm_client, "transcribe_audio", return_value=" ."):
            result = voice_memo.save_voice_memo(db, b"wav", None, wav_file)

        assert result["status"] == "empty"
        row = db.get_activity_by_id(result["activity_id"])
        assert row["summary"] == voice_memo.FALLBACK_UNAVAILABLE
        assert row["details"] == str(wav_file)

    def test_transcription_error_still_saves(self, db, wav_file):
        with patch.object(voice_memo.llm_client, "transcribe_audio", side_effect=RuntimeError("boom")):
            result = voice_memo.save_voice_memo(db, b"wav", None, wav_file)

        assert result["status"] == "failed"
        row = db.get_activity_by_id(result["activity_id"])
        assert row["summary"] == voice_memo.FALLBACK_FAILED
        assert row["details"] == str(wav_file)

    def test_cancelled_does_not_save(self, db, wav_file):
        with patch.object(voice_memo.llm_client, "transcribe_audio", return_value="hello there"):
            result = voice_memo.save_voice_memo(db, b"wav", None, wav_file, is_cancelled=lambda: True)

        assert result is None
        assert db.get_activities_by_date(str(datetime.now().date())) == []


class TestRetranscribeMemo:
    def test_updates_transcript_keeps_wav_path(self, db, wav_file):
        activity_id = _memo_row(db, wav_file)
        with patch.object(voice_memo.llm_client, "transcribe_audio", return_value="New transcript text"):
            result = voice_memo.retranscribe_memo(db, activity_id, wav_file)

        assert result["status"] == "ok"
        row = db.get_activity_by_id(activity_id)
        assert row["summary"] == "New transcript text"
        assert row["ocr_text"] == "New transcript text"
        assert row["details"] == str(wav_file)
        assert row["analysis_method"] == "retranscribe"

    def test_empty_result_keeps_previous_transcript(self, db, wav_file):
        activity_id = _memo_row(db, wav_file, summary="Earlier transcript")
        with patch.object(voice_memo.llm_client, "transcribe_audio", return_value=""):
            result = voice_memo.retranscribe_memo(db, activity_id, wav_file)

        assert result["status"] == "empty"
        assert db.get_activity_by_id(activity_id)["summary"] == "Earlier transcript"


# ── POST /api/activities/{id}/reanalyze ────────────────────────────────

@pytest.fixture
def no_embedder(monkeypatch):
    monkeypatch.setattr(deps, "embedder", None)


@pytest.mark.asyncio
class TestReanalyzeEndpoint:
    async def test_memo_is_retranscribed(self, client, db, wav_file):
        activity_id = _memo_row(db, wav_file)
        with patch("screenmind.engine.model_manager.is_audio_capable", return_value=True), \
             patch.object(voice_memo.llm_client, "transcribe_audio", return_value="Fresh transcript"):
            resp = await client.post(f"/api/activities/{activity_id}/reanalyze")

        assert resp.status_code == 200
        assert resp.json()["type"] == "voice_memo"
        row = db.get_activity_by_id(activity_id)
        assert row["summary"] == "Fresh transcript"
        assert row["details"] == str(wav_file)

    async def test_memo_missing_wav_returns_404(self, client, db, memos_dir):
        """A deleted WAV must not fall through to screenshot re-analysis."""
        activity_id = _memo_row(db, memos_dir / "2026-10-13" / "gone.wav")
        resp = await client.post(f"/api/activities/{activity_id}/reanalyze")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Audio file not found"
        assert db.get_activity_by_id(activity_id)["summary"] == "old summary"

    async def test_memo_without_audio_model_returns_409(self, client, db, wav_file):
        activity_id = _memo_row(db, wav_file)
        with patch("screenmind.engine.model_manager.is_audio_capable", return_value=False):
            resp = await client.post(f"/api/activities/{activity_id}/reanalyze")

        assert resp.status_code == 409

    async def test_memo_no_speech_returns_422(self, client, db, wav_file):
        activity_id = _memo_row(db, wav_file)
        with patch("screenmind.engine.model_manager.is_audio_capable", return_value=True), \
             patch.object(voice_memo.llm_client, "transcribe_audio", return_value=""):
            resp = await client.post(f"/api/activities/{activity_id}/reanalyze")

        assert resp.status_code == 422

    async def test_wav_outside_memos_dir_is_not_a_memo(self, client, db, tmp_path, memos_dir):
        """Only WAVs under the memos directory route to re-transcription."""
        stray = tmp_path / "stray.wav"
        stray.write_bytes(b"x")
        activity_id = _memo_row(db, stray)
        resp = await client.post(f"/api/activities/{activity_id}/reanalyze")

        # Treated as a screenshot row — which has no screenshot file
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Screenshot not found"

    async def test_screenshot_keeps_ocr_boxes_and_url(self, client, db, tmp_path, no_embedder):
        shot = tmp_path / "shot.jpg"
        Image.new("RGB", (200, 100), "white").save(shot)
        boxes = json.dumps([{"box": [[0, 0], [50, 0], [50, 10], [0, 10]], "text": "hello", "conf": 0.9}])
        activity_id = db.insert_activity(ScreenshotEntry(
            timestamp=datetime.now(),
            screenshot_path=str(shot),
            window_title="Docs - Google Chrome",
            detected_app_name="chrome",
        ))
        db.update_activity_analysis(
            activity_id, ActivityRecord(app_name="Chrome", activity_summary="old"),
            ocr_text="hello world", ocr_boxes=boxes, active_url="https://example.com/doc",
        )

        new_record = ActivityRecord(app_name="Chrome", activity_category="browsing",
                                    activity_summary="Reading a doc")
        with patch("screenmind.engine.analyzer.GemmaAnalyzer.analyze_screenshot_fast",
                   return_value=(new_record, [])) as analyze, \
             patch("screenmind.engine.analyzer.GemmaAnalyzer.analyze_screenshot_balanced",
                   return_value=(new_record, [])), \
             patch("screenmind.engine.analyzer.GemmaAnalyzer.analyze_screenshot",
                   return_value=(new_record, [])):
            resp = await client.post(f"/api/activities/{activity_id}/reanalyze")

        assert resp.status_code == 200, resp.text
        row = db.get_activity_by_id(activity_id)
        assert row["summary"] == "Reading a doc"
        assert row["ocr_boxes"] == boxes
        assert row["active_url"] == "https://example.com/doc"
        assert row["analysis_method"] == "reanalyze"


# ── GET /api/memos/{id}/audio ──────────────────────────────────────────

@pytest.mark.asyncio
class TestMemoAudioEndpoint:
    @pytest.fixture(autouse=True)
    def _memos_route_db(self, db, monkeypatch):
        import screenmind.api.routes.memos as memos_route
        monkeypatch.setattr(memos_route, "db", db)

    async def test_serves_memo_wav(self, client, db, wav_file):
        activity_id = _memo_row(db, wav_file)
        resp = await client.get(f"/api/memos/{activity_id}/audio")
        assert resp.status_code == 200
        assert resp.content == wav_file.read_bytes()

    async def test_refuses_path_outside_memos_dir(self, client, db, tmp_path, memos_dir):
        stray = tmp_path / "stray.wav"
        stray.write_bytes(b"x")
        activity_id = _memo_row(db, stray)
        resp = await client.get(f"/api/memos/{activity_id}/audio")
        assert resp.status_code == 404


# ── is_voice_memo flag + file cleanup on delete ───────────────────────

@pytest.mark.asyncio
class TestVoiceMemoFlag:
    async def test_activity_and_timeline_report_memo_flag(self, client, db, wav_file):
        memo_id = _memo_row(db, wav_file)
        shot_id = db.insert_activity(ScreenshotEntry(timestamp=datetime.now(), screenshot_path="/tmp/s.jpg"))
        db.update_activity_analysis(shot_id, ActivityRecord(detailed_context="Editing song.wav in Audacity"))

        assert (await client.get(f"/api/activity/{memo_id}")).json()["is_voice_memo"] is True
        assert (await client.get(f"/api/activity/{shot_id}")).json()["is_voice_memo"] is False

        today = str(datetime.now().date())
        flags = {a["id"]: a["is_voice_memo"]
                 for a in (await client.get(f"/api/timeline?date={today}")).json()["activities"]}
        assert flags == {memo_id: True, shot_id: False}


@pytest.mark.asyncio
class TestDeleteRemovesFiles:
    async def test_delete_memo_removes_wav_and_screenshot(self, client, db, wav_file, tmp_path):
        shot = tmp_path / "shot.jpg"
        shot.write_bytes(b"jpg")
        memo_id = _memo_row(db, wav_file)
        db._get_conn().execute("UPDATE activities SET screenshot_path = ? WHERE id = ?", (str(shot), memo_id))
        db._get_conn().commit()

        resp = await client.delete(f"/api/activities/{memo_id}")
        assert resp.status_code == 200
        assert not wav_file.exists()
        assert not shot.exists()

    async def test_delete_missing_activity_404(self, client):
        assert (await client.delete("/api/activities/999999")).status_code == 404

    async def test_clear_timeline_removes_memo_wavs(self, client, db, wav_file):
        _memo_row(db, wav_file)
        today = str(datetime.now().date())
        resp = await client.delete(f"/api/timeline/clear?date={today}")
        assert resp.json()["deleted"] == 1
        assert not wav_file.exists()
