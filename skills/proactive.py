"""
skills/proactive.py — Proactive background monitoring for J.A.R.V.I.S.

Runs as an APScheduler job. Checks:
  • CPU usage > threshold → alert
  • Battery < threshold  → alert
  • Due reminders        → speak aloud
  
Also exposes check_reminders() for the reminder-specific scheduler job.
"""

import logging
from datetime import datetime

import psutil  # type: ignore

from config import CPU_ALERT_THRESHOLD, BATTERY_ALERT_THRESHOLD
from memory.db import get_due_reminders, mark_reminder_triggered

logger = logging.getLogger(__name__)

# ── State to prevent repeated alerts ─────────────────────────────────────────
_last_cpu_alert: float = 0.0
_last_battery_alert: float = 0.0
_CPU_ALERT_COOLDOWN: float = 300.0     # 5 minutes between CPU alerts
_BATTERY_ALERT_COOLDOWN: float = 600.0  # 10 minutes between battery alerts


def check_system_resources(speak_fn=None) -> None:
    """
    Check CPU and battery. Speak an alert if thresholds are breached.
    speak_fn: callable that takes a string — usually core.speaker.speak_async_fire
    """
    global _last_cpu_alert, _last_battery_alert
    now = datetime.now().timestamp()

    # ── CPU ───────────────────────────────────────────────────────────────────
    try:
        cpu = psutil.cpu_percent(interval=1)
        if cpu > CPU_ALERT_THRESHOLD:
            if now - _last_cpu_alert > _CPU_ALERT_COOLDOWN:
                msg = (
                    f"A word of caution, Sir. CPU usage has reached {cpu:.0f}%, "
                    "which may indicate a runaway process. "
                    "You may wish to inspect the Task Manager."
                )
                logger.warning("Proactive CPU alert: %.0f%%", cpu)
                if speak_fn:
                    speak_fn(msg)
                _last_cpu_alert = now
    except Exception as exc:
        logger.error("Proactive CPU check error: %s", exc)

    # ── Battery ───────────────────────────────────────────────────────────────
    try:
        battery = psutil.sensors_battery()
        if battery and not battery.power_plugged:
            pct = battery.percent
            if pct < BATTERY_ALERT_THRESHOLD:
                if now - _last_battery_alert > _BATTERY_ALERT_COOLDOWN:
                    msg = (
                        f"Sir, the battery level has dropped to {pct:.0f}%. "
                        "I strongly recommend connecting to a power source."
                    )
                    logger.warning("Proactive battery alert: %.0f%%", pct)
                    if speak_fn:
                        speak_fn(msg)
                    _last_battery_alert = now
    except Exception as exc:
        logger.error("Proactive battery check error: %s", exc)


def check_reminders(speak_fn=None) -> None:
    """
    Fire any due reminders via TTS and mark them as triggered in the database.
    speak_fn: callable that takes a string.
    """
    try:
        due = get_due_reminders()
        for reminder in due:
            msg = f"Reminder, Sir: {reminder['title']}"
            logger.info("Firing reminder id=%s: %s", reminder["id"], reminder["title"])
            if speak_fn:
                speak_fn(msg)
            mark_reminder_triggered(reminder["id"])
    except Exception as exc:
        logger.error("check_reminders error: %s", exc)
