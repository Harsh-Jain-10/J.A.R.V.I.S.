"""
core/intent_router.py — Classify user input into one of JARVIS's skill intents.

Priority:
  1. Fast keyword matching (no API call, instant)
  2. LLM classification via brain.classify_intent() (only if ambiguous)

FIXES applied in this version:
  FIX-R1: Added "screen shot" (two words), "take screen shot", "capture screen"
           to SYSTEM_CONTROL so Whisper mis-splits don't fall through to FILE_OPS.
  FIX-R2: Added fuzzy_classify() — a second-pass normaliser that catches common
           Whisper phonetic mishearings BEFORE sending to the LLM. This saves
           an API round-trip on very common mis-transcriptions.
  FIX-R3: Added more voice-natural variants for all intents (e.g. "show me",
  1. Fast keyword matching (no API call, instant) for critical system commands
  2. LLM classification via brain.classify_intent() for all other intents

Intent labels:
  CHAT | WEB_SEARCH | WEATHER | NEWS | OPEN_APP | SYSTEM_CONTROL |
  FILE_OPS | REMINDER | BROWSER | MEMORY_RECALL
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Critical local command keywords to keep local and instant
_SYSTEM_CONTROL_KEYWORDS = [
    # Screenshot variants (English)
    "screenshot", "screen shot", "screen capture", "take a screenshot",
    "take screenshot", "take screen shot", "take a screen shot", "capture the screen",
    "capture screen", "get a screenshot",
    # Screenshot variants (Hinglish / Hindi)
    "screenshot lo", "screenshot le", "screenshot lelo", "screenshot lele",
    "screenshot kar", "screenshot karo", "screen capture karo", "capture karo",
    "photo le", "photo lo", "screen photo",
    # Hindi Devanagari
    "स्क्रीनशॉट", "स्क्रीन कैप्चर",
    # Volume
    "volume up", "volume down", "set volume", "mute", "unmute",
    "turn up the volume", "turn down the volume", "increase volume", "decrease volume",
    "lower the volume", "volume badhao", "volume kam karo", "volume band karo",
    # System info
    "system info", "cpu usage", "ram usage", "battery",
    "how much ram", "how much cpu", "memory usage",
    # Power / lock
    "shutdown", "restart", "reboot", "lock", "lock screen", "sleep mode",
    "turn off the computer", "shut down", "band karo", "band kar",
    # App close
    "close ", "close app", "quit ", "kill "
]

_OPEN_APP_KEYWORDS = [
    "chrome", "notepad", "calculator", "spotify", "discord", "vscode", "vs code",
    "word", "excel", "powerpoint", "explorer", "task manager"
]

# Fast-path CHAT keywords — these must NEVER hit the LLM classifier.
# They are simple, deterministic questions that the brain.ask() handles perfectly.
_CHAT_KEYWORDS = [
    # Date / time (critical fix — was being mis-routed to SYSTEM_CONTROL)
    "what is the date", "what's the date", "today's date", "date today",
    "what is today", "what day is it", "what day is today", "which day is today",
    "what is the time", "what's the time", "current time", "time now",
    "what time is it", "tell me the time", "what is today's date",
    "aaj kya date hai", "aaj kaunsa din hai", "kya time hai",
    "date and time", "time and date", "current date and time", "current time and date",
    "what is time", "what is date", "current time", "current date", "tell me time", "tell me date",
    "tell the time", "tell the date",
    # Greetings / small-talk
    "hello", "hi jarvis", "hey", "good morning", "good evening", "good night",
    "how are you", "what's up", "kya haal",
    # Self-referential
    "who are you", "what can you do", "your name",
]


# Fast-path NEWS keywords
_NEWS_KEYWORDS = [
    "news", "headlines", "latest news", "top stories", "what's happening",
    "khabar", "samachar",
]

# Fast-path WEATHER keywords (supplement to LLM)
_WEATHER_KEYWORDS = [
    "weather", "temperature", "forecast", "humidity", "rain", "sunny",
    "mausam", "garmi", "sardi",
]

_VALID_INTENTS = {
    "CHAT", "WEB_SEARCH", "WEATHER", "NEWS", "OPEN_APP",
    "SYSTEM_CONTROL", "FILE_OPS", "REMINDER", "BROWSER",
    "MEMORY_RECALL",
}

# Fuzzy maps for phonetic mishearings
_FUZZY_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b6\s+screen\s*shot\b", re.I),  "take a screenshot"),
    (re.compile(r"\bscreen\s+shot\b", re.I),        "screenshot"),
    (re.compile(r"\bscripts?\b", re.I),             "screenshot"),
    (re.compile(r"\bscreenshots?\b", re.I),          "screenshot"),
    (re.compile(r"\btake\s+screen\s*shot\b", re.I), "take a screenshot"),
    (re.compile(r"\bvolume\s+app\b", re.I),         "volume up"),
    (re.compile(r"\bbolume\b", re.I),               "volume"),
    (re.compile(r"\bmew+t\b", re.I),                "mute"),
    (re.compile(r"\bwhether\b", re.I),              "weather"),
    (re.compile(r"\bwhather\b", re.I),              "weather"),
    (re.compile(r"\bremember\s+me\s+to\b", re.I),   "remind me to"),
    (re.compile(r"\bcalc\s+later\b", re.I),         "calculator"),
    (re.compile(r"\bnote\s+pad\b", re.I),           "notepad"),
    (re.compile(r"\byou\s+tube\b", re.I),           "youtube"),
    (re.compile(r"\block\s+the\s+screen\b", re.I),  "lock screen"),
    (re.compile(r"\block\s+my\s+screen\b", re.I),   "lock screen"),
    (re.compile(r"\bsystem\s+information\b", re.I), "system info"),
    (re.compile(r"\bclose\s+the\s+app\b", re.I),    "close app"),
    (re.compile(r"\bquit\s+the\s+app\b", re.I),     "quit app"),
    # Hinglish phonetic variants
    (re.compile(r"\bscreenshot\s+(lo|le|lelo|lele|kar|karo)\b", re.I), "screenshot"),
    (re.compile(r"\bscreen\s+capture\s+karo\b", re.I),               "screenshot"),
    (re.compile(r"\bcapture\s+karo\b", re.I),                         "screenshot"),
    (re.compile(r"\bphoto\s+(le|lo)\b", re.I),                        "screenshot"),
    (re.compile(r"\bvolume\s+badh(ao|a)\b", re.I),                    "volume up"),
    (re.compile(r"\bvolume\s+kam\s+karo\b", re.I),                    "volume down"),
    (re.compile(r"\bvolume\s+band\s+karo?\b", re.I),                  "mute"),
    (re.compile(r"\bchrome\s+kholo\b", re.I),                         "open chrome"),
    (re.compile(r"\bnotepad\s+kholo\b", re.I),                        "open notepad"),
]


def _fuzzy_normalize(text: str) -> str:
    """Apply phonetic/mishearing normalisation to Whisper output."""
    normalised = text
    for pattern, replacement in _FUZZY_MAP:
        normalised = pattern.sub(replacement, normalised)
    if normalised != text:
        logger.debug("Fuzzy normalised: '%s' → '%s'", text, normalised)
    return normalised


def _llm_classify(text: str, brain) -> str:
    """Ask the LLM to classify the intent. Falls back to CHAT on failure."""
    try:
        label = brain.classify_intent(text).strip().upper()
        for candidate in _VALID_INTENTS:
            if candidate in label:
                logger.debug("LLM classified intent: %s", candidate)
                # Overrule NEWS if it's a general query with no news keywords
                if candidate == "NEWS":
                    news_kws = ["news", "headline", "stories", "happening", "khabar", "samachar"]
                    if not any(kw in text.lower() for kw in news_kws):
                        logger.debug("NEWS overrule: no news keyword found, redirecting to WEB_SEARCH")
                        return "WEB_SEARCH"
                return candidate
    except Exception as exc:
        logger.error("LLM intent classification failed: %s", exc)
    return "CHAT"


def route(text: str, brain=None) -> str:
    """
    Main entry point.
    Returns the intent string for the given user input.
    Uses keywords only for critical system/app controls, LLM for everything else.
    """
    if not text:
        return "CHAT"

    # Apply fuzzy normalization first
    normalised = _fuzzy_normalize(text)
    lowered = normalised.lower()

    # 1. CHAT fast-path — date/time/greetings never go to the LLM classifier
    for kw in _CHAT_KEYWORDS:
        if kw in lowered:
            logger.debug("CHAT fast-path keyword match: '%s'", kw)
            return "CHAT"

    # 2. Check for critical SYSTEM_CONTROL commands
    for kw in _SYSTEM_CONTROL_KEYWORDS:
        if kw in lowered:
            logger.debug("System control keyword match: '%s'", kw)
            return "SYSTEM_CONTROL"

    # 3. Check for OPEN_APP commands (must include "open" or "launch" + app name)
    if any(action in lowered for action in ["open", "launch", "start", "run", "switch to"]):
        for app in _OPEN_APP_KEYWORDS:
            if app in lowered:
                logger.debug("Open app keyword match: '%s'", app)
                return "OPEN_APP"

    # 4. NEWS fast-path
    for kw in _NEWS_KEYWORDS:
        if kw in lowered:
            logger.debug("NEWS fast-path keyword match: '%s'", kw)
            return "NEWS"

    # 5. WEATHER fast-path
    for kw in _WEATHER_KEYWORDS:
        if kw in lowered:
            logger.debug("WEATHER fast-path keyword match: '%s'", kw)
            return "WEATHER"

    # 6. Route all other intents semantically via the LLM
    if brain is not None:
        return _llm_classify(normalised, brain)

    logger.debug("No intent matched — defaulting to CHAT.")
    return "CHAT"