"""
Files that belong to activities: screenshots and voice memo recordings.

Activity rows store absolute paths — `screenshot_path` for the image and,
for voice memos, the WAV path in `details`. Deleting a row must delete
these files too, or they outlive the user's delete / retention setting.
"""

import logging
import re
import shutil
from pathlib import Path
from typing import Optional

from screenmind.config import settings

logger = logging.getLogger("screenmind.storage.files")

# Screenshot and memo files are grouped in YYYY-MM-DD folders
_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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


def is_voice_memo(activity: dict) -> bool:
    """True if an activity row (dict) is a voice memo."""
    return memo_wav_path(activity.get("details")) is not None


def _unlink(path: Path):
    try:
        if path.exists():
            path.unlink()
    except OSError as e:
        logger.debug(f"Could not delete {path}: {e}")


def delete_activity_files(screenshot_path: Optional[str], details: Optional[str]):
    """Delete the screenshot and, for voice memos, the WAV of one activity."""
    if screenshot_path:
        _unlink(Path(screenshot_path))
    wav = memo_wav_path(details)
    if wav is not None:
        _unlink(wav)


def remove_date_dirs(root: Path, before_date: Optional[str] = None):
    """Clean up YYYY-MM-DD folders under `root`.

    Empty folders are always removed. With `before_date` (YYYY-MM-DD),
    folders for earlier dates are removed with their contents — this also
    catches files whose activity row was lost (e.g. after a crash).
    """
    if not root.exists():
        return
    for d in root.iterdir():
        if not d.is_dir() or not _DATE_DIR_RE.match(d.name):
            continue
        try:
            if before_date and d.name < before_date:
                shutil.rmtree(d)
            elif not any(d.iterdir()):
                d.rmdir()
        except OSError as e:
            logger.debug(f"Could not remove {d}: {e}")
