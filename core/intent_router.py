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
           "what's the weather like", "can you open", "pull up", etc.)
  FIX-R4: FILE_OPS no longer matches bare "open " — only "open file" / "read file"
           etc. This stops "open notepad" from being swallowed by FILE_OPS.

Intent labels:
  CHAT | WEB_SEARCH | WEATHER | NEWS | OPEN_APP | SYSTEM_CONTROL |
  FILE_OPS | REMINDER | BROWSER | IMAGE_ANALYSIS | MEMORY_RECALL
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ── Keyword maps ──────────────────────────────────────────────────────────────
# Order matters: more specific patterns come first.

_KEYWORD_MAP: list[tuple[str, list[str]]] = [
    ("IMAGE_ANALYSIS", [
        "analyze image", "analyse image", "look at image", "describe image",
        "what's in this image", "look at this photo", "image analysis",
        "what is in this photo", "look at this picture",
    ]),
    ("MEMORY_RECALL", [
        "what did we talk about", "what did i tell you", "recall",
        "do you remember", "previous conversation", "our history",
        "what did we discuss", "what did i ask", "first question",
        "last question", "what was my", "what did i say",
    ]),
    ("REMINDER", [
        "remind me", "set a reminder", "alert me", "set alarm",
        "don't let me forget", "schedule reminder", "add a reminder",
    ]),
    ("WEATHER", [
        "weather", "temperature", "forecast", "rain", "humid",
        "wind speed", "how hot", "how cold", "celsius", "fahrenheit",
        "what's the weather", "what is the weather", "weather like",
        "is it going to rain", "will it rain", "climate today",
    ]),
    ("NEWS", [
        "news", "headlines", "latest news", "top stories",
        "what's happening", "current events", "tell me the news",
        "show me the news", "what happened today",
    ]),
    ("WEB_SEARCH", [
        "search for", "search the web", "look up", "google it", "google search",
        "find information about", "wikipedia", "search online",
        "find out about", "tell me about", "who is", "what is",
    ]),
    ("BROWSER", [
        "open browser", "open url", "go to website", "open website",
        "browse", "navigate to", "youtube", "visit",
        "clipboard", "copy this", "paste",
        "go to", "take me to",
    ]),
    # FIX-R4: FILE_OPS only matches "open FILE" / "read file" etc — NOT bare "open "
    # This prevents "open notepad" from routing here.
    ("FILE_OPS", [
        "find file", "search file", "open file", "read file",
        "list files", "list folder", "show directory", "delete file",
        "summarize file", "what's in this file", "list directory",
        "show files in", "show folder",
    ]),
    ("SYSTEM_CONTROL", [
        # FIX-R1: Added two-word variants that Whisper commonly produces
        "screenshot", "screen shot", "screen capture",
        "take a screenshot", "take screenshot", "take screen shot",
        "take a screen shot", "capture the screen", "capture screen",
        "get a screenshot",
        # Volume
        "volume up", "volume down", "set volume", "mute", "unmute",
        "turn up the volume", "turn down the volume", "increase volume",
        "decrease volume", "lower the volume",
        # System info
        "system info", "cpu usage", "ram usage", "battery",
        "how much ram", "how much cpu", "memory usage",
        # Power
        "shutdown", "restart", "reboot", "lock", "lock screen",
        "sleep mode", "turn off the computer", "shut down",
        # Close app
        "close ", "close app", "quit ", "exit the", "kill ",
    ]),
    ("OPEN_APP", [
        # Specific apps first
        "google chrome", "open chrome", "launch chrome",
        "open whatsapp", "launch whatsapp",
        "open spotify", "open discord", "open notepad", "open calculator",
        "open vs code", "open vscode", "open edge", "open firefox",
        "open word", "open excel", "open powerpoint",
        "open task manager", "open file explorer",
        # FIX-R3: Added natural voice variants
        "can you open", "please open", "pull up", "bring up",
        "start up", "fire up",
        # Generic openers (after specific app names)
        "open ", "launch ", "start ", "run ",
        "switch to",
    ]),
]

# Intent labels that are valid LLM responses
_VALID_INTENTS = {
    "CHAT", "WEB_SEARCH", "WEATHER", "NEWS", "OPEN_APP",
    "SYSTEM_CONTROL", "FILE_OPS", "REMINDER", "BROWSER",
    "IMAGE_ANALYSIS", "MEMORY_RECALL",
}


# ── Fuzzy phonetic normalisation ──────────────────────────────────────────────
# FIX-R2: Common Whisper mishearings mapped to their correct form.
# Applied BEFORE keyword matching so mis-transcribed commands still route correctly.
# Format: (regex_pattern, replacement)

_FUZZY_MAP: list[tuple[re.Pattern, str]] = [
    # Screenshot variants
    (re.compile(r"\b6\s+screen\s*shot\b", re.I),  "take a screenshot"),
    (re.compile(r"\bscreen\s+shot\b", re.I),        "screenshot"),
    (re.compile(r"\bscreenshots?\b", re.I),          "screenshot"),
    # "take" + screenshot
    (re.compile(r"\btake\s+screen\s*shot\b", re.I), "take a screenshot"),
    # Volume
    (re.compile(r"\bvolume\s+app\b", re.I),         "volume up"),
    (re.compile(r"\bbolume\b", re.I),               "volume"),
    (re.compile(r"\bmew+t\b", re.I),                "mute"),
    # Weather
    (re.compile(r"\bwhether\b", re.I),              "weather"),
    (re.compile(r"\bwhather\b", re.I),              "weather"),
    # Reminder
    (re.compile(r"\bremember\s+me\s+to\b", re.I),   "remind me to"),
    # Calculator
    (re.compile(r"\bcalc\s+later\b", re.I),         "calculator"),
    # Notepad
    (re.compile(r"\bnote\s+pad\b", re.I),           "notepad"),
    # YouTube
    (re.compile(r"\byou\s+tube\b", re.I),           "youtube"),
    # Lock screen
    (re.compile(r"\block\s+the\s+screen\b", re.I),  "lock screen"),
    (re.compile(r"\block\s+my\s+screen\b", re.I),   "lock screen"),
    # System info
    (re.compile(r"\bsystem\s+information\b", re.I), "system info"),
    # Close app
    (re.compile(r"\bclose\s+the\s+app\b", re.I),    "close app"),
    (re.compile(r"\bquit\s+the\s+app\b", re.I),     "quit app"),
]


def _fuzzy_normalize(text: str) -> str:
    """
    Apply phonetic/mishearing normalisation to Whisper output.
    Returns a cleaned version of the text for more reliable keyword matching.
    """
    normalised = text
    for pattern, replacement in _FUZZY_MAP:
        normalised = pattern.sub(replacement, normalised)
    if normalised != text:
        logger.debug("Fuzzy normalised: '%s' → '%s'", text, normalised)
    return normalised


def _keyword_classify(text: str) -> Optional[str]:
    """
    Try to match the text against keyword patterns.
    Returns an intent string or None if ambiguous.
    Applies fuzzy normalisation first (FIX-R2).
    """
    # FIX-R2: normalise before matching
    normalised = _fuzzy_normalize(text)
    lowered = normalised.lower()

    for intent, keywords in _KEYWORD_MAP:
        for kw in keywords:
            if kw in lowered:
                logger.debug("Keyword match: '%s' → %s", kw, intent)
                return intent
    return None


def _llm_classify(text: str, brain) -> str:
    """
    Ask the LLM to classify the intent.
    Falls back to CHAT on failure.
    """
    try:
        label = brain.classify_intent(text).strip().upper()
        for candidate in _VALID_INTENTS:
            if candidate in label:
                logger.debug("LLM classified intent: %s", candidate)
                return candidate
    except Exception as exc:
        logger.error("LLM intent classification failed: %s", exc)
    return "CHAT"


def route(text: str, brain=None) -> str:
    """
    Main entry point.
    Returns the intent string for the given user input.
    """
    if not text:
        return "CHAT"

    # ── Fast path: keyword matching (with fuzzy normalisation) ────────────────
    intent = _keyword_classify(text)
    if intent:
        return intent

    # ── Slow path: LLM classification ─────────────────────────────────────────
    if brain is not None:
        return _llm_classify(text, brain)

    logger.debug("No intent matched — defaulting to CHAT.")
    return "CHAT"