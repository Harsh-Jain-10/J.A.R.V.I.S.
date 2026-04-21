"""
config.py — Central configuration for J.A.R.V.I.S.
All tunable settings live here; secrets come from .env via python-dotenv.
"""

import os
from dotenv import load_dotenv

# ── Load .env file ────────────────────────────────────────────────────────────
load_dotenv()

# ── Identity ──────────────────────────────────────────────────────────────────
USER_NAME: str = os.getenv("USER_NAME", "Sir")
CITY: str = os.getenv("CITY", "London")

# ── API Keys ──────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
OPENWEATHER_API_KEY: str = os.getenv("OPENWEATHER_API_KEY", "")
NEWS_API_KEY: str = os.getenv("NEWS_API_KEY", "")

# ── Groq 
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


# ── Gemini (fallback LLM )
GEMINI_MODEL: str = "gemini-2.0-flash"

# ── Voice / STT ───────────────────────────────────────────────────────────────
WHISPER_MODEL: str = "base"      # tiny | base | small | medium | large
WAKE_WORDS: list[str] = ["hey jarvis", "jarvis"]
MIC_ENERGY_THRESHOLD: int = 300  # calibrated automatically on startup
SPEECH_PHRASE_TIMEOUT: float = 3.0   
SPEECH_TIMEOUT: float = 10.0

# ── TTS ───────────────────────────────────────────────────────────────────────
TTS_VOICE: str = "en-GB-RyanNeural" 
TTS_RATE: str = "-8%"       # Slightly slower = more authoritative, less robotic
TTS_VOLUME: str = "+0%"
TTS_OUTPUT_FILE: str = "jarvis_tts_output.mp3"


USER_NAME_PHONETIC: str = os.getenv("USER_NAME_PHONETIC", USER_NAME)

# ── Memory ────────────────────────────────────────────────────────────────────
DB_PATH: str = "jarvis_memory.db"
CONTEXT_RECENT_MESSAGES: int = 10   # last N messages from today
CONTEXT_DAILY_SUMMARIES: int = 3    # last N day summaries

# ── Personality system prompt ─────────────────────────────────────────────────
SYSTEM_PROMPT: str = (
    "You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), the AI assistant. "
    "You speak in a formal, intelligent, and slightly witty British tone. "
    "You always address the user as 'Sir'. "
    "You are concise but complete. You never say you are an AI language model. "
    "You have memory of past conversations which will be provided to you. "
    "You are capable, confident, and occasionally use dry humor."
)

# ── Proactive Alerts ──────────────────────────────────────────────────────────
CPU_ALERT_THRESHOLD: int = 90        # % CPU usage
BATTERY_ALERT_THRESHOLD: int = 20    # % battery remaining
PROACTIVE_CHECK_INTERVAL: int = 60   # seconds between proactive checks

# ── Scheduler ─────────────────────────────────────────────────────────────────
NIGHTLY_SUMMARY_HOUR: int = 23
NIGHTLY_SUMMARY_MINUTE: int = 59
REMINDER_CHECK_INTERVAL: int = 60    # seconds

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = "INFO"
LOG_FILE: str = "jarvis.log"
