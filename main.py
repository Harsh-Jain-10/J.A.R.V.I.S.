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
from memory.db import initialize_db, save_conversation
from memory.db import dismiss_stale_reminders
from core.brain import Brain
from core.intent_router import route
from core.speaker import speak, speak_async_fire, PRIORITY_CHAT, PRIORITY_ALERT, PRIORITY_MONITOR
from core.dialogue_state import dialogue_state, WAITING_REMINDER_TIME
from core.listener import WakeWordListener
from ui.ws_bridge import ui_bridge

# ── Skills ────────────────────────────────────────────────────────────────────
from skills import (
    web_search,
    weather,
    news,
    system_control,
    file_ops,
    calendar_skill,
    browser_control,
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
      1. Check FSM: if we're waiting for a follow-up, resolve it and return.
      2. Classify intent → route to skill or brain → speak → save to DB.
    """
    if not user_text.strip():
        return

    logger.info("Handling: '%s'", user_text)

    # ── Update UI Bridge ──────────────────────────────────────────────────────
    try:
        ui_bridge.add_transcript("You", user_text)
        ui_bridge.update_state("THINKING")
    except Exception:
        pass

    # ── FSM Follow-up check (multi-turn dialogue) ────────────────────────────
    # If JARVIS is mid-conversation (e.g. asked "When, Sir?"), handle it here
    # before reclassifying as a new intent.
    if dialogue_state.is_waiting():
        logger.info("DialogueState: resolving follow-up in state '%s'", dialogue_state.state)
        followup_response = dialogue_state.handle_followup(user_text)
        if followup_response:
            speak(followup_response, priority=PRIORITY_CHAT)
            try:
                save_conversation(user_text, followup_response)
            except Exception as exc:
                logger.error("Failed to save follow-up conversation: %s", exc)
            return

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
            # ── FSM: if time was missing, ask for it and set follow-up state ──
            _REMINDER_MISSING_TIME_PHRASES = [
                "couldn't determine the time",
                "couldn't parse a time",
                "please say something like",
            ]
            if any(phrase in response for phrase in _REMINDER_MISSING_TIME_PHRASES):
                from skills.calendar_skill import _extract_title
                title = _extract_title(user_text)
                # Transition FSM → waiting for the time
                dialogue_state.expect(WAITING_REMINDER_TIME, {"title": title})
                # Override the canned error message with a friendlier question
                response = (
                    f"I've noted '{title}', Sir. "
                    f"When would you like me to remind you? "
                    f"You can say something like 'in 10 minutes' or 'at 3 PM'."
                )

        elif intent == "BROWSER":
            response = browser_control.handle(user_text, brain)


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
    # If the user spoke a skill query but their vocal emotion was detected as angry/sad/etc.,
    # we can append an empathetic remark from J.A.R.V.I.S.
    try:
        import core.listener as listener
        if listener.LATEST_EMOTION and listener.LATEST_EMOTION.lower() not in ["calm", "neutral", "quiet"]:
            # Only append to non-chat intents (skills) since CHAT already incorporates emotion in response
            if intent not in ["CHAT", "MEMORY_RECALL"]:
                emotion_clean = listener.LATEST_EMOTION.lower()
                if "angry" in emotion_clean or "frustrated" in emotion_clean:
                    response += " I hope that is satisfactory, Sir. Though, if I may say so, you sound rather vexed. Is everything alright?"
                elif "sad" in emotion_clean or "tired" in emotion_clean:
                    response += " I hope this is of assistance, Sir. I noticed you sound a bit down today. Please let me know if there is anything I can do to help."
                elif "happy" in emotion_clean or "excited" in emotion_clean:
                    response += " Splendid, Sir! I am glad to hear you in such high spirits."
                elif "hesitant" in emotion_clean:
                    response += " Please let me know if you would like me to clarify or adjust anything, Sir."
        # Clear the emotion after consumption
        listener.LATEST_EMOTION = None
    except Exception as exc:
        logger.warning("Failed to inject emotion-specific prefix/suffix: %s", exc)

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
        func=lambda: proactive.check_reminders(
            speak_fn=lambda t: speak_async_fire(t, priority=PRIORITY_ALERT)
        ),
        trigger=IntervalTrigger(seconds=REMINDER_CHECK_INTERVAL),
        id="reminder_check",
        name="Reminder Checker",
        replace_existing=True,
    )

    # ── Proactive system monitor (every 60 seconds) ────────────────────────────
    scheduler.add_job(
        func=lambda: proactive.check_system_resources(
            speak_fn=lambda t: speak_async_fire(t, priority=PRIORITY_MONITOR)
        ),
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

    # ── Step 1a: Start UI WebSocket Bridge ──────────────────────────────────────
    try:
        ui_bridge._on_command = handle_input
        ui_bridge.start_in_thread()
    except Exception as exc:
        logger.warning("Failed to start UI WebSocket Bridge: %s", exc)

    # ── Step 1b: Clear stale overdue reminders from previous sessions ───────────
    # Reminders more than 10 minutes overdue are silently dismissed so they
    # don't all fire simultaneously the moment JARVIS boots up.
    dismissed = dismiss_stale_reminders()
    if dismissed:
        print(f"[STARTUP] Silently dismissed {dismissed} overdue reminder(s) from previous session.", flush=True)

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
                import os
                import webbrowser
                base_dir = os.path.dirname(os.path.abspath(__file__))
                ui_html_path = os.path.join(base_dir, "ui", "index.html")
                webbrowser.open(f"file:///{ui_html_path.replace(os.sep, '/')}")
            except Exception as web_exc:
                logger.warning("Could not automatically open UI index.html: %s", web_exc)

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
