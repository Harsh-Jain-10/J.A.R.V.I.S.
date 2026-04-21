"""
main.py — J.A.R.V.I.S. Entry Point

Starts:
  1. SQLite database initialisation
  2. Brain (multi-LLM)
  3. APScheduler (reminders, nightly summary, proactive alerts)
  4. Wake-word listener thread
  5. Main conversation loop
"""

import logging
import sys
import time
from datetime import datetime

# ── Logging setup (before any imports that use it) ────────────────────────────
from config import LOG_LEVEL, LOG_FILE, USER_NAME

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("JARVIS")

# ── Core imports ──────────────────────────────────────────────────────────────
from memory.db import initialize_db
from core.brain import Brain
from core.speaker import speak, speak_async_fire
from core.listener import WakeWordListener, listen_once
from core.intent_router import route
from memory.db import save_conversation

# ── Skills ────────────────────────────────────────────────────────────────────
from skills import (
    web_search,
    weather,
    news,
    system_control,
    file_ops,
    calendar_skill,
    browser_control,
    image_input,
    proactive,
)

# ── Scheduler ─────────────────────────────────────────────────────────────────
from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
from apscheduler.triggers.cron import CronTrigger  # type: ignore
from apscheduler.triggers.interval import IntervalTrigger  # type: ignore
from config import (
    NIGHTLY_SUMMARY_HOUR,
    NIGHTLY_SUMMARY_MINUTE,
    REMINDER_CHECK_INTERVAL,
    PROACTIVE_CHECK_INTERVAL,
)
from memory.summarizer import run_nightly_summarization


# ─────────────────────────────────────────────────────────────────────────────
# Global state
# ─────────────────────────────────────────────────────────────────────────────

brain: Brain = None  # type: ignore
_running: bool = True


# ─────────────────────────────────────────────────────────────────────────────
# Core response pipeline
# ─────────────────────────────────────────────────────────────────────────────

def handle_input(user_text: str) -> None:
    """
    Process one utterance from the user end-to-end:
      classify intent → route to skill or brain → speak → save to DB.
    """
    if not user_text.strip():
        return

    logger.info("Handling: '%s'", user_text)

    # ── Classify intent ───────────────────────────────────────────────────────
    intent = route(user_text, brain)
    logger.info("Intent: %s", intent)

    response = ""

    try:
        # ── Route to appropriate skill ────────────────────────────────────────
        if intent == "WEATHER":
            response = weather.handle(user_text, brain)

        elif intent == "NEWS":
            response = news.handle(user_text, brain)

        elif intent == "WEB_SEARCH":
            response = web_search.handle(user_text, brain)

        elif intent == "OPEN_APP" or intent == "SYSTEM_CONTROL":
            response = system_control.handle(user_text, brain)

        elif intent == "FILE_OPS":
            response = file_ops.handle(user_text, brain)

        elif intent == "REMINDER":
            response = calendar_skill.handle(user_text, brain)

        elif intent == "BROWSER":
            response = browser_control.handle(user_text, brain)

        elif intent == "IMAGE_ANALYSIS":
            response = image_input.handle(user_text, brain)

        elif intent == "MEMORY_RECALL":
            # Ask brain with full memory context — context_manager handles this
            response = brain.ask(user_text)

        else:  # CHAT (default)
            response = brain.ask(user_text)

    except Exception as exc:
        logger.error("Skill error for intent '%s': %s", intent, exc)
        response = (
            f"I'm afraid I encountered an error handling that request, Sir: {exc}. "
            "Please try again."
        )

    if not response:
        response = "I'm sorry, Sir, I didn't receive a response. Please try again."

    # ── Speak and persist ─────────────────────────────────────────────────────
    speak(response)
    try:
        save_conversation(user_text, response)
    except Exception as exc:
        logger.error("Failed to save conversation: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler setup
# ─────────────────────────────────────────────────────────────────────────────

def _setup_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()

    # ── Reminder checker (every minute) ────────────────────────────────────────
    scheduler.add_job(
        func=lambda: proactive.check_reminders(speak_fn=speak_async_fire),
        trigger=IntervalTrigger(seconds=REMINDER_CHECK_INTERVAL),
        id="reminder_check",
        name="Reminder Checker",
        replace_existing=True,
    )

    # ── Proactive system monitor (every 60 seconds) ────────────────────────────
    scheduler.add_job(
        func=lambda: proactive.check_system_resources(speak_fn=speak_async_fire),
        trigger=IntervalTrigger(seconds=PROACTIVE_CHECK_INTERVAL),
        id="proactive_monitor",
        name="Proactive System Monitor",
        replace_existing=True,
    )

    # ── Nightly summarizer ─────────────────────────────────────────────────────
    scheduler.add_job(
        func=lambda: run_nightly_summarization(brain),
        trigger=CronTrigger(hour=NIGHTLY_SUMMARY_HOUR, minute=NIGHTLY_SUMMARY_MINUTE),
        id="nightly_summary",
        name="Nightly Summarizer",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("APScheduler started with %d jobs.", len(scheduler.get_jobs()))
    return scheduler


# ─────────────────────────────────────────────────────────────────────────────
# Wake-word callback
# ─────────────────────────────────────────────────────────────────────────────

def _on_wake_word(command_text: str) -> None:
    """Called by the WakeWordListener thread each time a command is captured."""
    handle_input(command_text)


# ─────────────────────────────────────────────────────────────────────────────
# Text-mode REPL (for testing without a microphone)
# ─────────────────────────────────────────────────────────────────────────────

def _run_text_mode() -> None:
    """Interactive text REPL — type commands, press Enter."""
    speak("J.A.R.V.I.S. system online and fully operational. Text mode active, Sir.")
    print("\n" + "="*60)
    print("  J.A.R.V.I.S. — Text Mode")
    print("  Type your command and press Enter. Type 'exit' to quit.")
    print("="*60 + "\n")

    while _running:
        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit", "bye", "goodbye"}:
                speak("Goodbye, Sir. Powering down.")
                break
            handle_input(user_input)
        except (KeyboardInterrupt, EOFError):
            speak("Goodbye, Sir.")
            break


# ─────────────────────────────────────────────────────────────────────────────
# Voice mode
# ─────────────────────────────────────────────────────────────────────────────

def _run_voice_mode() -> None:
    """Start wake-word listener and run until KeyboardInterrupt."""
    speak(
        "J.A.R.V.I.S. system online and fully operational. "
        "I am listening for your wake word, Sir."
    )

    listener = WakeWordListener(callback=_on_wake_word)
    listener.start()
    logger.info("Voice mode active. Say '%s' to wake me.", " or ".join(["hey jarvis", "jarvis"]))

    try:
        while _running:
            time.sleep(1)
    except KeyboardInterrupt:
        listener.stop()
        speak("Initiating shutdown sequence. Goodbye, Sir.")
        logger.info("JARVIS is shutting down.")


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    global brain

    logger.info("=" * 60)
    logger.info("  J.A.R.V.I.S. Starting Up — %s", datetime.now().isoformat())
    logger.info("=" * 60)

    # ── Step 1: Initialise database ───────────────────────────────────────────
    initialize_db()

    # ── Step 2: Initialise brain ──────────────────────────────────────────────
    brain = Brain()

    # ── Step 3: Start APScheduler ─────────────────────────────────────────────
    scheduler = _setup_scheduler()

    # ── Step 4: Choose mode ───────────────────────────────────────────────────
    use_text_mode = "--text" in sys.argv or "--debug" in sys.argv

    try:
        if use_text_mode:
            _run_text_mode()
        else:
            try:
                _run_voice_mode()
            except Exception as exc:
                logger.error("Voice mode failed: %s — falling back to text mode.", exc)
                _run_text_mode()
    finally:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down. JARVIS offline.")


if __name__ == "__main__":
    main()
