"""
core/dialogue_state.py — Finite State Machine for multi-turn conversations.

States:
  IDLE                    — No active follow-up needed.
  WAITING_REMINDER_TIME   — A reminder title was captured; waiting for time.
  WAITING_REMINDER_TITLE  — Time captured; waiting for what to remind.
  WAITING_SEARCH_QUERY    — User said "search" with no query.
  WAITING_WEATHER_CITY    — User asked weather with no city.

Usage (in main.py):
    from core.dialogue_state import dialogue_state

    # Before routing intent:
    if dialogue_state.is_waiting():
        result = dialogue_state.handle_followup(user_text)
        if result:
            speak(result)
            return

    # After a skill returns a follow-up prompt:
    if needs_followup:
        dialogue_state.expect("WAITING_REMINDER_TIME", {"title": title})
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Valid states ───────────────────────────────────────────────────────────────

IDLE                  = "IDLE"
WAITING_REMINDER_TIME  = "WAITING_REMINDER_TIME"
WAITING_REMINDER_TITLE = "WAITING_REMINDER_TITLE"
WAITING_SEARCH_QUERY  = "WAITING_SEARCH_QUERY"
WAITING_WEATHER_CITY  = "WAITING_WEATHER_CITY"


class DialogueState:
    """
    Thread-safe finite state machine for multi-turn dialogue.

    The state machine tracks what JARVIS is waiting for next.
    When `is_waiting()` returns True, `handle_followup()` processes
    the next user utterance as a continuation of the previous turn
    instead of starting a fresh intent classification.
    """

    def __init__(self) -> None:
        self._state: str = IDLE
        self._context: dict[str, Any] = {}

    # ── State inspection ──────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        return self._state

    def is_waiting(self) -> bool:
        """Return True if JARVIS is in the middle of a multi-turn exchange."""
        return self._state != IDLE

    def get_context(self, key: str, default: Any = None) -> Any:
        return self._context.get(key, default)

    # ── State transitions ─────────────────────────────────────────────────────

    def expect(self, next_state: str, context: Optional[dict] = None) -> None:
        """
        Transition to a new state, storing context for the follow-up handler.
        Called by skill handlers when they need more information.
        """
        logger.info("DialogueState: %s → %s  context=%s", self._state, next_state, context)
        self._state = next_state
        self._context = context or {}

    def clear(self) -> None:
        """Reset to IDLE after a follow-up is resolved or cancelled."""
        if self._state != IDLE:
            logger.info("DialogueState: %s → IDLE", self._state)
        self._state = IDLE
        self._context = {}

    # ── Follow-up handler ─────────────────────────────────────────────────────

    def handle_followup(self, user_text: str) -> Optional[str]:
        """
        Process a user utterance as a follow-up to the current waiting state.

        Returns:
            str  — JARVIS's response if the follow-up was resolved.
            None — if the state is IDLE (should not normally be called).
        """
        if self._state == IDLE:
            return None

        # ── WAITING_REMINDER_TIME ─────────────────────────────────────────────
        if self._state == WAITING_REMINDER_TIME:
            return self._resolve_reminder_time(user_text)

        # ── WAITING_REMINDER_TITLE ────────────────────────────────────────────
        if self._state == WAITING_REMINDER_TITLE:
            return self._resolve_reminder_title(user_text)

        # ── WAITING_SEARCH_QUERY ──────────────────────────────────────────────
        if self._state == WAITING_SEARCH_QUERY:
            return self._resolve_search_query(user_text)

        # ── WAITING_WEATHER_CITY ──────────────────────────────────────────────
        if self._state == WAITING_WEATHER_CITY:
            return self._resolve_weather_city(user_text)

        # Unknown state — reset safely
        logger.warning("DialogueState: unknown state '%s' — resetting.", self._state)
        self.clear()
        return None

    # ── Resolvers ─────────────────────────────────────────────────────────────

    def _resolve_reminder_time(self, user_text: str) -> str:
        """User has provided the time for a pending reminder."""
        from skills.calendar_skill import _parse_datetime
        from memory.db import add_reminder

        title = self._context.get("title", "Reminder")
        dt = _parse_datetime(user_text)

        if dt is None:
            # Still no time — try asking one more time
            return (
                f"I still couldn't parse a time from that, Sir. "
                f"Could you say something like 'in 10 minutes' or 'at 3 PM'?"
            )

        rid = add_reminder(title, dt)
        self.clear()
        if rid > 0:
            return (
                f"Done, Sir. I've set a reminder for '{title}' "
                f"on {dt.strftime('%A, %d %B at %I:%M %p')}."
            )
        return "I was unable to save the reminder, Sir. Please try again."

    def _resolve_reminder_title(self, user_text: str) -> str:
        """User provided the reminder title when it was missing."""
        from skills.calendar_skill import _parse_datetime
        from memory.db import add_reminder

        # The stored context has the datetime already
        dt = self._context.get("datetime")
        title = user_text.strip().capitalize()

        if not title:
            self.clear()
            return "I didn't catch that, Sir. Reminder cancelled."

        if dt is None:
            # Now we have title but no time — flip to waiting for time
            self.expect(WAITING_REMINDER_TIME, {"title": title})
            return f"Understood. When would you like me to remind you about '{title}', Sir?"

        rid = add_reminder(title, dt)
        self.clear()
        if rid > 0:
            return (
                f"Reminder set, Sir. I'll alert you to '{title}' "
                f"on {dt.strftime('%A, %d %B at %I:%M %p')}."
            )
        return "I was unable to save the reminder, Sir."

    def _resolve_search_query(self, user_text: str) -> str:
        """User provided the search query they want."""
        from skills import web_search
        self.clear()
        return web_search.handle(user_text)

    def _resolve_weather_city(self, user_text: str) -> str:
        """User provided the city for a weather query."""
        from skills import weather
        self.clear()
        return weather.handle(f"weather in {user_text}")


# ── Module-level singleton ─────────────────────────────────────────────────────

dialogue_state = DialogueState()
