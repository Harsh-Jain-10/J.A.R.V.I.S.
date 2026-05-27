"""
memory/summarizer.py — Nightly conversation summarizer for J.A.R.V.I.S.

Scheduled to run at 23:59 every night via APScheduler (set up in main.py).
Pulls all of today's conversations, sends them to Gemini/Ollama for a
5-bullet summary, and stores the result in the summaries table.
"""

import logging
from datetime import date
from memory.db import get_conversations_for_date, save_summary

logger = logging.getLogger(__name__)


def _build_summary_prompt(conversations: list[dict]) -> str:
    """Build the prompt to send to the LLM for summarization."""
    lines = ["Summarize the following conversation between a user and JARVIS in exactly 5 concise bullet points. Focus on what was discussed, requested, and accomplished.\n"]
    for entry in conversations:
        lines.append(f"User: {entry['user_input']}")
        lines.append(f"JARVIS: {entry['jarvis_response']}\n")
    lines.append("\nProvide ONLY the 5 bullet points, no intro or outro text.")
    return "\n".join(lines)


def run_nightly_summarization(brain=None) -> None:
    """
    Entry point called by APScheduler.
    Summarises today's conversations and saves the result.

    Args:
        brain: The Brain instance (passed from main.py) to call the LLM.
    """
    today = date.today().isoformat()
    logger.info("Nightly summarizer running for %s …", today)

    conversations = get_conversations_for_date(today)
    if not conversations:
        logger.info("No conversations to summarise for %s.", today)
        return

    prompt = _build_summary_prompt(conversations)

    summary_text = ""
    if brain is not None:
        try:
            # Use brain directly — skip memory injection for meta-task
            summary_text = brain.ask_raw(prompt)
        except Exception as exc:
            logger.error("Brain summarization failed: %s", exc)

    if not summary_text:
        # Fallback: create a basic summary from the conversation list
        summary_text = _fallback_summary(conversations)

    save_summary(today, summary_text)
    logger.info("Nightly summary saved for %s.", today)


def _fallback_summary(conversations: list[dict]) -> str:
    """
    Ultra-simple fallback if the LLM is unreachable.
    Extracts topic keywords from user inputs.
    """
    topics = []
    for c in conversations[:10]:
        snippet = c["user_input"][:80].strip()
        topics.append(f"• {snippet}")
    return "\n".join(topics) if topics else "• No notable conversations recorded."
