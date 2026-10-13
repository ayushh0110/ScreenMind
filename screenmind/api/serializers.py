"""Shape activity rows for the dashboard API responses."""

from screenmind.storage.files import is_voice_memo


def add_display_fields(activity: dict) -> dict:
    """Add fields the dashboard needs: screenshot URL and the voice-memo flag."""
    if activity.get("screenshot_path"):
        activity["screenshot_url"] = f"/api/screenshot/{activity['id']}"
    activity["is_voice_memo"] = is_voice_memo(activity)
    return activity
