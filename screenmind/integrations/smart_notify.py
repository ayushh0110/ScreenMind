"""
Smart Notifications
Detects usage patterns and shows overlay notifications.
- Distraction alerts (too long on entertainment apps)
- Break reminders (continuous work without switching)
- Focus streak celebrations
"""

import logging
import time
from typing import Optional

from screenmind.config import settings

logger = logging.getLogger("screenmind.integrations.smart_notify")

# Entertainment app keywords
ENTERTAINMENT_APPS = {"youtube", "netflix", "twitch", "reddit", "twitter", "instagram", "tiktok", "facebook", "x.com"}

# Cooldown tracking — don't spam the same notification type
_last_notification = {}  # type -> timestamp
COOLDOWN_SECONDS = 30 * 60  # 30 minutes between same notification type

# Tracking state
_app_start_time = {}  # app_name -> first_seen_timestamp
_last_app = None
_continuous_work_start = None


def check(app_name: str, category: str = ""):
    """
    Check if a notification should be shown based on current app usage.
    Called every capture tick (~5-30s), before the capture is analyzed.

    Args:
        app_name: Current foreground app name.
        category: Activity category (coding, browsing, etc.), if already
            known. When given, the focus-streak check runs too.
    """
    global _last_app, _continuous_work_start

    if not settings.smart_notifications:
        return

    now = time.time()
    app_lower = (app_name or "").lower()

    # Track app duration
    if app_lower != _last_app:
        _app_start_time[app_lower] = now
        _last_app = app_lower

        # Reset continuous work timer on app switch
        if _continuous_work_start and (now - _continuous_work_start) > settings.break_reminder_minutes * 60:
            # They switched after a long session — that's good!
            _continuous_work_start = now
        elif not _continuous_work_start:
            _continuous_work_start = now
    
    # 1. Distraction alert
    if any(ent in app_lower for ent in ENTERTAINMENT_APPS):
        duration = now - _app_start_time.get(app_lower, now)
        minutes = duration / 60
        if minutes >= settings.distraction_minutes:
            _notify(
                "distraction",
                "⏰ Time Check",
                f"You've been on {app_name} for {int(minutes)} minutes.",
                color="#f59e0b",
            )

    # 2. Break reminder
    if _continuous_work_start:
        continuous_minutes = (now - _continuous_work_start) / 60
        if continuous_minutes >= settings.break_reminder_minutes:
            _notify(
                "break",
                "☕ Break Time",
                f"You've been working for {int(continuous_minutes)} minutes. Consider a short break.",
                color="#10b981",
            )
            _continuous_work_start = now  # Reset after showing

    # 3. Focus streak — needs the category, which capture-time callers don't have
    if category:
        check_focus(app_name, category)


def check_focus(app_name: str, category: str):
    """
    Celebrate a focus streak (2+ hours of coding in one app session).

    Called by the analysis worker once a capture's category is known. Uses
    the app-session start time tracked by check(), and only fires while that
    app is still the current foreground app.
    """
    if not settings.smart_notifications or category != "coding":
        return

    app_lower = (app_name or "").lower()
    if app_lower != _last_app or app_lower not in _app_start_time:
        return  # Not the current app session

    coding_minutes = (time.time() - _app_start_time[app_lower]) / 60
    if coding_minutes >= 120:
        _notify(
            "focus",
            "🔥 Focus Streak!",
            f"{int(coding_minutes)} minutes of deep coding. Impressive!",
            color="#8b5cf6",
        )


def _notify(notification_type: str, title: str, message: str, color: str = "#8b5cf6"):
    """Show notification with cooldown check."""
    now = time.time()
    last = _last_notification.get(notification_type, 0)

    if now - last < COOLDOWN_SECONDS:
        return  # Still in cooldown

    _last_notification[notification_type] = now

    try:
        from screenmind.ui.overlay import show_overlay_notification
        show_overlay_notification(title, message, duration=5.0, color=color)
    except Exception as e:
        logger.error(f"{title}: {message} (overlay failed: {e})")
