"""
memory/context_manager.py — Builds the memory context block injected into every LLM call.

Pulls:
  • Last N conversations from today         (config.CONTEXT_RECENT_MESSAGES)
  • Last M daily summaries from past days   (config.CONTEXT_DAILY_SUMMARIES)
"""

import logging
from memory.db import get_today_conversations, get_recent_summaries
from config import CONTEXT_RECENT_MESSAGES, CONTEXT_DAILY_SUMMARIES

logger = logging.getLogger(__name__)


def build_context_block() -> str:
    """
    Return a formatted string representing JARVIS's memory context.
    This string is prepended to the user's message before sending to the LLM.
    """
    sections: list[str] = []

    # ── Recent conversations from today ───────────────────────────────────────
    try:
        today_convos = get_today_conversations(limit=CONTEXT_RECENT_MESSAGES)
        if today_convos:
            lines = ["[MEMORY — Today's Conversation History]"]
            for entry in today_convos:
                ts = entry.get("timestamp", "")
                lines.append(f"  [{ts}] User: {entry['user_input']}")
                lines.append(f"          JARVIS: {entry['jarvis_response']}")
            sections.append("\n".join(lines))
    except Exception as exc:
        logger.error("Error fetching today's conversations: %s", exc)

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
