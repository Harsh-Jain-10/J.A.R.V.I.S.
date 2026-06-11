"""
memory/context_manager.py — Builds the memory context block injected into every LLM call.

Pulls:
  • Last N conversations from today         (config.CONTEXT_RECENT_MESSAGES)
  • Last M daily summaries from past days   (config.CONTEXT_DAILY_SUMMARIES)
"""

import logging
from memory.db import (
    get_session_conversations,
    get_today_conversations_before_session,
    get_recent_summaries,
)
from config import CONTEXT_RECENT_MESSAGES, CONTEXT_DAILY_SUMMARIES, SESSION_START

logger = logging.getLogger(__name__)


def build_context_block() -> str:
    """
    Return a formatted string representing JARVIS's memory context.
    This string is prepended to the user's message before sending to the LLM.
    """
    sections: list[str] = []

    # ── Today's Conversations (Current Session + Earlier Today) ───────────────
    try:
        session_convos = get_session_conversations(SESSION_START)
    except Exception as exc:
        logger.error("Error fetching session conversations: %s", exc)
        session_convos = []

    try:
        earlier_convos = get_today_conversations_before_session(SESSION_START, limit=CONTEXT_RECENT_MESSAGES)
    except Exception as exc:
        logger.error("Error fetching earlier today's conversations: %s", exc)
        earlier_convos = []

    if earlier_convos or session_convos:
        lines = ["[MEMORY — Today's Conversation History]"]
        if earlier_convos:
            lines.append("  (Earlier Sessions Today)")
            for entry in earlier_convos:
                ts = entry.get("timestamp", "")
                lines.append(f"  [{ts}] User: {entry['user_input']}")
                lines.append(f"          JARVIS: {entry['jarvis_response']}")
            if session_convos:
                lines.append("")  # Empty line separator between sessions
        if session_convos:
            lines.append("  (Current Session)")
            for entry in session_convos:
                ts = entry.get("timestamp", "")
                lines.append(f"  [{ts}] User: {entry['user_input']}")
                lines.append(f"          JARVIS: {entry['jarvis_response']}")
        sections.append("\n".join(lines))

    # ── Past daily summaries ──────────────────────────────────────────────────
    try:
        summaries = get_recent_summaries(limit=CONTEXT_DAILY_SUMMARIES)
        if summaries:
            lines = ["[MEMORY — Recent Daily Summaries]"]
            for s in summaries:
                lines.append(f"  {s['date']}: {s['summary']}")
            sections.append("\n".join(lines))
    except Exception as exc:
        logger.error("Error fetching recent summaries: %s", exc)

    if not sections:
        return ""  # No context yet (e.g., first run)

    header = "=== JARVIS CONTEXTUAL MEMORY ==="
    footer = "=== END OF MEMORY CONTEXT ==="
    return f"{header}\n" + "\n\n".join(sections) + f"\n{footer}\n"


def get_full_prompt(user_message: str) -> str:
    """
    Combines memory context + user message into the final prompt string
    that gets sent to the LLM (after the system prompt is handled separately).
    """
    context = build_context_block()
    if context:
        return f"{context}\n\nUser: {user_message}"
    return f"User: {user_message}"
