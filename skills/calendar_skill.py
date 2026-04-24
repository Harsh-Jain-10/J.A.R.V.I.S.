
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from memory.db import add_reminder, list_upcoming_reminders

logger = logging.getLogger(__name__)

def _parse_datetime(query: str) -> Optional[datetime]:
    """
    Attempt to parse a datetime from natural language.
    Handles: 'at 3pm', 'at 15:30', 'at 12.34pm' (Whisper uses period not colon),
             'in 10 minutes', 'after 10 seconds', 'tomorrow at 9am', 'in 2 hours'.
    Returns None if parsing fails.
    """
    now = datetime.now()
    # Normalise Whisper quirk: 'at 12.34pm' → 'at 12:34pm'
    lower = re.sub(r'(\d{1,2})\.(\d{2})\s*(am|pm)', r'\1:\2\3', query.lower())

    # ── Relative: "in/after X seconds/minutes/hours" ──────────────────────────
    rel_match = re.search(
        r'(?:in|after)\s+(\d+)\s+(second|seconds|sec|minute|minutes|min|hour|hours|hr)',
        lower,
    )
    if rel_match:
        amount = int(rel_match.group(1))
        unit = rel_match.group(2)
        if "sec" in unit:
            return now + timedelta(seconds=amount)
        if "hour" in unit or "hr" in unit:
            return now + timedelta(hours=amount)
        return now + timedelta(minutes=amount)

    # ── "tomorrow at HH:MM am/pm" ─────────────────────────────────────────────
    tomorrow = now + timedelta(days=1)
    if "tomorrow" in lower:
        time_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", lower)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            ampm = time_match.group(3)
            if ampm == "pm" and hour != 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            return tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)

    # ── "at HH:MM am/pm" (today) ──────────────────────────────────────────────
    at_match = re.search(r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", lower)
    if at_match:
        hour = int(at_match.group(1))
        minute = int(at_match.group(2) or 0)
        ampm = at_match.group(3)
        if ampm == "pm" and hour != 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate < now:
            candidate += timedelta(days=1)
        return candidate

    return None


def _extract_title(query: str) -> str:
    """Extract reminder title from query like 'remind me to drink water at 3pm'."""
    lower = query.lower()
    patterns = [
        r"remind me to (.+?) (?:at|in|on|every)",
        r"remind me to (.+?)$",
        r"set (?:a )?reminder (?:for|to) (.+?) (?:at|in|on|every)",
        r"set (?:a )?reminder (?:for|to) (.+?)$",
        r"alert me (?:to|about|when) (.+?) (?:at|in)",
    ]
    for pat in patterns:
        m = re.search(pat, lower)
        if m:
            return m.group(1).strip().capitalize()
    # Fallback: strip known lead-in phrases
    for phrase in ["remind me to ", "remind me ", "set reminder ", "set a reminder "]:
        if phrase in lower:
            idx = lower.index(phrase) + len(phrase)
            return query[idx:].strip().capitalize()
    return "Reminder"


def handle(query: str, brain=None) -> str:
    lowered = query.lower()

    # ── List reminders ─────────────────────────────────────────────────────────
    if "list" in lowered or "show" in lowered or "what reminders" in lowered:
        upcoming = list_upcoming_reminders(limit=5)
        if not upcoming:
            return "You have no upcoming reminders, Sir."
        lines = ["Your upcoming reminders:"]
        for r in upcoming:
            lines.append(f"  • {r['title']} — {r['datetime']}")
        return "\n".join(lines)

    # ── Add reminder ───────────────────────────────────────────────────────────
    if any(kw in lowered for kw in ["remind me", "set reminder", "set a reminder", "alert me"]):
        title = _extract_title(query)
        dt = _parse_datetime(query)
        if dt is None:
            return (
                "I understood you'd like a reminder, but I couldn't determine the time, Sir. "
                "Please say something like 'remind me to call John at 3pm'."
            )
        rid = add_reminder(title, dt)
        if rid > 0:
            return (
                f"Reminder set, Sir. I'll alert you to '{title}' "
                f"on {dt.strftime('%A, %d %B %Y at %I:%M %p')}."
            )
        return "I was unable to save the reminder, Sir. Please try again."

    return "I can set and list reminders for you, Sir. Just say 'remind me to ...' or 'show my reminders'."
