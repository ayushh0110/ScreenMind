"""
Voice Memo Storage
Transcribes voice memos with Gemma 4's audio encoder and stores them as
activities. Shared by the voice hotkey (main.py) and the re-transcribe
endpoint (api/routes/timeline.py).

A memo row stores:
  - summary:   first 200 chars of the transcript (or a fallback message)
  - ocr_text:  the full transcript (indexed by FTS5, read by chat)
  - details:   absolute path to the WAV file under <data_dir>/memos/
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from screenmind.config import settings
from screenmind.engine import llm_client
from screenmind.storage.models import ActivityRecord, ScreenshotEntry

logger = logging.getLogger("screenmind.engine.voice_memo")

MEMO_APP_NAME = "Voice Memo"
SUMMARY_MAX_CHARS = 200
FALLBACK_UNAVAILABLE = "Voice memo (transcription unavailable)"
FALLBACK_FAILED = "Voice memo (transcription failed)"

# Shorter transcripts are treated as empty (noise, a single filler word)
_MIN_TRANSCRIPT_CHARS = 3


def memos_dir() -> Path:
    """Directory where voice memo WAV files are stored."""
    return settings.data_path / "memos"


def memo_wav_path(details: Optional[str]) -> Optional[Path]:
    """Return the memo WAV path stored in an activity's details, or None.

    Screenshot activities keep Gemma's free-text description in `details`,
    so a value only counts as a memo when it is a .wav path that resolves
    inside the memos directory. The file itself may no longer exist.
    """
    if not details or not isinstance(details, str):
        return None
    text = details.strip()
    if not text.lower().endswith(".wav"):
        return None
    try:
        path = Path(text).resolve()
        path.relative_to(memos_dir().resolve())
    except (ValueError, OSError):
        return None
    return path


def transcribe(wav_bytes: bytes) -> str:
    """Transcribe WAV audio. Returns "" when nothing usable was recognized.

    Raises on inference errors, including ValueError when the active model
    has no audio encoder.
    """
    transcript = (llm_client.transcribe_audio(wav_bytes) or "").strip()
    return transcript if len(transcript) >= _MIN_TRANSCRIPT_CHARS else ""


def _memo_record(summary: str, wav_path: Path, confidence: float) -> ActivityRecord:
    return ActivityRecord(
        app_name=MEMO_APP_NAME,
        activity_category="other",
        activity_summary=summary,
        detailed_context=str(wav_path),
        mood="neutral",
        confidence=confidence,
    )


def _store_transcript(db, activity_id: int, transcript: str, wav_path: Path, method: str):
    db.update_activity_analysis(
        activity_id,
        _memo_record(transcript[:SUMMARY_MAX_CHARS], wav_path, confidence=0.9),
        ocr_text=transcript,
        analysis_method=method,
    )


def save_voice_memo(
    db,
    wav_bytes: bytes,
    screenshot_path: Optional[Path],
    wav_path: Path,
    is_cancelled: Callable[[], bool] = lambda: False,
) -> Optional[dict]:
    """Transcribe a new voice memo and store it as a bookmarked activity.

    The memo is always saved, even when transcription fails, so the audio
    and screenshot stay available for playback.

    Args:
        is_cancelled: Checked before writing to the database (e.g. shutdown).

    Returns:
        {"activity_id", "status": "ok" | "empty" | "failed", "transcript"},
        or None if cancelled before saving.
    """
    try:
        transcript = transcribe(wav_bytes)
        status = "ok" if transcript else "empty"
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        transcript, status = "", "failed"

    if is_cancelled():
        logger.info("Shutdown in progress — discarding memo")
        return None

    activity_id = db.insert_activity(ScreenshotEntry(
        timestamp=datetime.now(),
        screenshot_path=str(screenshot_path) if screenshot_path else "",
        window_title=MEMO_APP_NAME,
        detected_app_name=MEMO_APP_NAME,
        bookmarked=True,
        analyzed=False,
    ))

    if status == "ok":
        _store_transcript(db, activity_id, transcript, wav_path, method="voice_memo")
        logger.info(f"Saved: {transcript[:60]}...")
    else:
        fallback = FALLBACK_UNAVAILABLE if status == "empty" else FALLBACK_FAILED
        db.update_activity_analysis(
            activity_id,
            _memo_record(fallback, wav_path, confidence=0.1),
            analysis_method="voice_memo",
        )
        logger.warning(f"Saved voice memo without transcript ({status})")

    return {"activity_id": activity_id, "status": status, "transcript": transcript}


def retranscribe_memo(db, activity_id: int, wav_path: Path) -> dict:
    """Re-run transcription on an existing memo's WAV file.

    The row is only updated when a transcript comes back, so a failed or
    empty retry never replaces an earlier transcript.

    Returns:
        {"status": "ok" | "empty", "transcript"}. Raises on inference errors.
    """
    transcript = transcribe(wav_path.read_bytes())
    if not transcript:
        return {"status": "empty", "transcript": ""}
    _store_transcript(db, activity_id, transcript, wav_path, method="retranscribe")
    return {"status": "ok", "transcript": transcript}
