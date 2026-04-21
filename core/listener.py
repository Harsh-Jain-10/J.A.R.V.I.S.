"""
core/listener.py — Wake-word detection + STT for J.A.R.V.I.S.

FIXES applied in this version:
  FIX-L1: Whisper upgraded to 'small' model for much better accuracy.
  FIX-L2: Whisper initial_prompt added — primes it to expect JARVIS commands
           so it stops hallucinating random words like '6' or mishearing commands.
  FIX-L3: Post-transcription text normaliser strips Whisper hallucination
           artefacts (leading digits, punctuation noise, filler words).
  FIX-L4: SPEECH_START_THRESHOLD lowered from 400 → 300 so softer speech
           (especially the 'H' in 'Hey') is captured without clipping.
  FIX-L5: silence_duration reduced from 0.8s → 0.6s — removes the
           noticeable lag between you stopping speaking and JARVIS responding.
  FIX-L6: wait_for_speech_timeout after "Yes Sir?" reduced from 8s → 6s
           so the conversation mode feels more responsive.
  FIX-L7: Pre-buffer increased from 300ms → 500ms to avoid clipping the
           first syllable of commands.
  FIX-L8: audio_np length guard — skip transcription if audio is < 0.4s
           (Whisper hallucinates on near-silence chunks).
"""

import io
import logging
import queue
import re
import threading
import time
import wave
from typing import Callable, Optional

import numpy as np
import sounddevice as sd
import speech_recognition as sr

from config import (
    WAKE_WORDS,
    MIC_ENERGY_THRESHOLD,
    SPEECH_TIMEOUT,
    WHISPER_MODEL,
)

logger = logging.getLogger(__name__)

# ── Audio constants ───────────────────────────────────────────────────────────
SAMPLE_RATE = 16000   # Whisper and Google STT both expect 16 kHz
CHANNELS = 1
DTYPE = "int16"

# ── Threshold constants ───────────────────────────────────────────────────────
# FIX-L4: Lowered from 400 → 300. The 'H' in "Hey" and soft consonants at the
# start of words were being clipped. 300 still rejects ambient noise (RMS ~50-150)
# but captures natural speech more reliably.
SPEECH_START_THRESHOLD: int = 300

# SILENCE_END_THRESHOLD: stays at 150 — good balance between capturing word
# endings and not running on forever after speech stops.
SILENCE_END_THRESHOLD: int = 150

# FIX-L2: Whisper initial_prompt — primes the model to expect JARVIS-style
# commands. This dramatically reduces hallucinations like "6", "Thank you.",
# random punctuation, or completely wrong words on short utterances.
_WHISPER_INITIAL_PROMPT = (
    "JARVIS voice assistant commands: take a screenshot, open notepad, "
    "what is the weather, search for, remind me to, system info, "
    "set volume, open chrome, open calculator, play music, "
    "what time is it, lock the screen, close the app."
)

# ── Lazy-load Whisper so startup is fast ─────────────────────────────────────
_whisper_model = None
_whisper_lock = threading.Lock()

# FIX-L1: Read from config but override to 'small' minimum for acceptable accuracy.
# 'tiny' and 'base' produce too many transcription errors for command recognition.
_EFFECTIVE_WHISPER_MODEL = WHISPER_MODEL if WHISPER_MODEL in ("small", "medium", "large") else "small"


def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        with _whisper_lock:
            if _whisper_model is None:
                try:
                    import whisper  # type: ignore
                    logger.info(
                        "Loading Whisper model '%s' (effective: '%s') …",
                        WHISPER_MODEL, _EFFECTIVE_WHISPER_MODEL,
                    )
                    _whisper_model = whisper.load_model(_EFFECTIVE_WHISPER_MODEL)
                    logger.info("Whisper model loaded.")
                except Exception as exc:
                    logger.error("Could not load Whisper: %s", exc)
                    _whisper_model = None
    return _whisper_model


# ── SpeechRecognition recognizer (for Google STT fallback) ───────────────────
_recognizer = sr.Recognizer()
_recognizer.energy_threshold = MIC_ENERGY_THRESHOLD
_recognizer.dynamic_energy_threshold = True
_recognizer.pause_threshold = 0.6


# ── Audio capture helpers ─────────────────────────────────────────────────────

def _record_audio(duration: float) -> np.ndarray:
    """
    Record *duration* seconds of audio from the default input device at 16 kHz.
    Returns a 1-D int16 numpy array.
    """
    frames = int(SAMPLE_RATE * duration)
    audio = sd.rec(frames, samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE)
    sd.wait()
    return audio.flatten()


def _numpy_to_audio_data(audio_np: np.ndarray) -> sr.AudioData:
    """Convert a numpy int16 array to a SpeechRecognition AudioData object."""
    raw_bytes = audio_np.tobytes()
    return sr.AudioData(raw_bytes, SAMPLE_RATE, 2)  # 2 bytes per int16 sample


def _record_until_silence(
    max_duration: float = 15.0,
    silence_duration: float = 0.6,   # FIX-L5: was 0.8 — 0.6 removes noticeable lag
    wait_for_speech_timeout: Optional[float] = None,
) -> np.ndarray:
    """
    Waits for the user to start speaking, then records until they stop.

    Two separate thresholds are used:
      - SPEECH_START_THRESHOLD (300): RMS must EXCEED this to BEGIN recording.
        FIX-L4: Lowered from 400 to catch softer speech starts.
      - SILENCE_END_THRESHOLD (150): RMS must DROP BELOW this to END recording.
        Lower than start threshold so soft consonants and word endings are
        captured before recording stops.

    Args:
        max_duration: Maximum recording time in seconds after speech starts.
        silence_duration: Seconds of continuous silence needed to stop recording.
                          FIX-L5: Reduced to 0.6s for snappier response.
        wait_for_speech_timeout: If set, bail out after this many seconds if the
                                 user hasn't started speaking. None = wait forever
                                 (used for the wake-word detection loop).
    """
    chunk_size = int(SAMPLE_RATE * 0.1)           # 100ms chunks
    max_chunks = int(max_duration / 0.1)
    silence_chunks_needed = int(silence_duration / 0.1)
    wait_chunks_max = (
        int(wait_for_speech_timeout / 0.1)
        if wait_for_speech_timeout is not None
        else None
    )

    import collections
    # FIX-L7: Pre-buffer increased from 300ms (3 chunks) → 500ms (5 chunks)
    # so the first syllable of commands is never clipped.
    pre_buffer_chunks = 5
    pre_buffer = collections.deque(maxlen=pre_buffer_chunks)

    frames: list[np.ndarray] = []
    has_spoken = False
    silent_chunks = 0
    waited_chunks = 0

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE) as stream:
        while True:
            chunk, _ = stream.read(chunk_size)
            chunk = chunk.flatten()
            rms = int(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))

            if not has_spoken:
                waited_chunks += 1
                if rms >= SPEECH_START_THRESHOLD:
                    has_spoken = True
                    frames.extend(pre_buffer)
                    frames.append(chunk)
                elif wait_chunks_max is not None and waited_chunks >= wait_chunks_max:
                    logger.debug(
                        "No speech detected within %.1fs — returning empty audio.",
                        wait_for_speech_timeout,
                    )
                    break
                else:
                    pre_buffer.append(chunk)
            else:
                frames.append(chunk)
                if rms < SILENCE_END_THRESHOLD:
                    silent_chunks += 1
                else:
                    silent_chunks = 0

                if silent_chunks >= silence_chunks_needed:
                    break

                if len(frames) >= max_chunks:
                    break

    return np.concatenate(frames) if frames else np.zeros(0, dtype=np.int16)


# ── Text post-processor ───────────────────────────────────────────────────────

# FIX-L3: Whisper hallucination patterns to strip from transcripts.
# Whisper commonly emits these on short/quiet audio clips.
_HALLUCINATION_PATTERNS = [
    r"^\s*\d+\s+",           # Leading digits like "6 screen shot" → "screen shot"
    r"^[\.\,\!\?\-\s]+",     # Leading punctuation
    r"[\.\,\!\?]+$",         # Trailing punctuation (keep structure words)
    r"\bthank you\.?\s*$",   # "Thank you." hallucination on silence
    r"\bbye\.?\s*$",         # "Bye." hallucination
    r"\bsubs by.*$",         # Subtitle artefacts
    r"\bsubtitles by.*$",
]

_HALLUCINATION_RE = [re.compile(p, re.IGNORECASE) for p in _HALLUCINATION_PATTERNS]

# Two-word → one-word normalisation for common Whisper splits
_WORD_JOIN_MAP = {
    "screen shot":  "screenshot",
    "screen shots": "screenshots",
    "note pad":     "notepad",
    "you tube":     "youtube",
    "what sapp":    "whatsapp",
    "calc later":   "calculator",
    "drop box":     "dropbox",
}


def _clean_transcript(text: str) -> str:
    """
    Apply post-processing to raw Whisper output:
      1. Strip hallucination artefacts (leading digits, punctuation noise).
      2. Join common two-word → one-word mis-splits.
    """
    cleaned = text.strip()
    for pattern in _HALLUCINATION_RE:
        cleaned = pattern.sub("", cleaned).strip()

    # Word-join normalisation (case-insensitive)
    lower = cleaned.lower()
    for two_word, one_word in _WORD_JOIN_MAP.items():
        lower = lower.replace(two_word, one_word)
    cleaned = lower  # return lowercase — intent router is already case-insensitive

    return cleaned.strip()


# ── Transcription ─────────────────────────────────────────────────────────────

# FIX-L8: Minimum audio length to bother transcribing — avoids Whisper
# hallucinating on near-silence (< 0.4 seconds of actual speech).
_MIN_AUDIO_SAMPLES = int(SAMPLE_RATE * 0.4)


def _transcribe_whisper(audio_np: np.ndarray) -> Optional[str]:
    """Transcribe a numpy int16 array using local Whisper model."""
    # FIX-L8: Skip very short clips — Whisper hallucinates on them.
    if len(audio_np) < _MIN_AUDIO_SAMPLES:
        logger.debug("Audio too short (%d samples) — skipping Whisper.", len(audio_np))
        return None

    model = _get_whisper()
    if model is None:
        return None
    try:
        float_audio = audio_np.astype(np.float32) / 32768.0
        # FIX-L2: initial_prompt primes Whisper to expect JARVIS commands.
        result = model.transcribe(
            float_audio,
            fp16=False,
            language="en",
            initial_prompt=_WHISPER_INITIAL_PROMPT,
        )
        raw_text = result.get("text", "").strip()
        logger.debug("Whisper raw: '%s'", raw_text)

        # FIX-L3: Clean the transcript before returning.
        text = _clean_transcript(raw_text)
        logger.debug("Whisper cleaned: '%s'", text)
        return text or None
    except Exception as exc:
        logger.error("Whisper transcription error: %s", exc)
        return None


def _transcribe_google(audio_np: np.ndarray) -> Optional[str]:
    """Transcribe using Google Speech Recognition (free tier, requires internet)."""
    if len(audio_np) < _MIN_AUDIO_SAMPLES:
        return None
    try:
        audio_data = _numpy_to_audio_data(audio_np)
        text = _recognizer.recognize_google(audio_data)
        logger.debug("Google STT: '%s'", text)
        return _clean_transcript(text) or None
    except sr.UnknownValueError:
        logger.debug("Google STT: could not understand audio.")
        return None
    except sr.RequestError as exc:
        logger.error("Google STT request error: %s", exc)
        return None


def transcribe(audio_np: np.ndarray) -> str:
    """
    Attempt Whisper first, fall back to Google STT.
    Returns empty string if both fail.
    """
    text = _transcribe_whisper(audio_np)
    if not text:
        logger.info("Whisper failed — trying Google STT …")
        text = _transcribe_google(audio_np)
    return text or ""


# ── Public API ────────────────────────────────────────────────────────────────

# FIX-L6: Conversation idle timeout unchanged at 20s — this is fine.
# But the first-command wait after "Yes Sir?" is reduced from 8s → 6s
# so it feels more responsive without being too short.
CONVERSATION_IDLE_TIMEOUT: float = 20.0
_FIRST_COMMAND_TIMEOUT: float = 6.0   # FIX-L6: was 8.0


def _wait_for_wake_word() -> str:
    """
    Passive mode: wait until the user says the wake word.
    Returns the command that followed the wake word (may be empty string).
    """
    logger.info("JARVIS in passive mode — waiting for wake word: %s", WAKE_WORDS)

    while True:
        try:
            audio = _record_until_silence(wait_for_speech_timeout=None)
            if len(audio) == 0:
                continue

            text = transcribe(audio)
            if not text:
                continue

            lowered = text.lower()
            for ww in WAKE_WORDS:
                if ww in lowered:
                    idx = lowered.find(ww)
                    command_text = text[idx + len(ww):].strip(" .,!?")
                    logger.info("Wake word detected. Inline command: '%s'", command_text)
                    return command_text

        except Exception as exc:
            logger.error("_wait_for_wake_word error: %s", exc)
            time.sleep(0.5)


def _listen_for_next_command(idle_timeout: float = CONVERSATION_IDLE_TIMEOUT) -> Optional[str]:
    """
    Active / conversation mode: listen directly for a command WITHOUT requiring
    the wake word. Returns None if silence timeout expires.
    """
    audio = _record_until_silence(
        max_duration=15.0,
        wait_for_speech_timeout=idle_timeout,
    )
    if len(audio) == 0:
        return None

    text = transcribe(audio).strip(" .,!?")
    return text if text else None


def listen_for_command() -> str:
    """
    Main entry point for the WakeWordListener thread.
    Handles one command and returns it.
    """
    from core.speaker import speak

    inline_command = _wait_for_wake_word()

    if inline_command:
        logger.info("User command captured: '%s'", inline_command)
        return inline_command

    speak("Yes, Sir?")
    logger.info("Awaiting command in conversation mode...")

    # FIX-L6: Use 6s instead of 8s for snappier feel
    first_cmd = _listen_for_next_command(idle_timeout=_FIRST_COMMAND_TIMEOUT)
    if first_cmd:
        logger.info("User command captured: '%s'", first_cmd)
        return first_cmd

    logger.debug("No command received after wake word — returning to passive mode.")
    return listen_for_command()


def listen_once(timeout: float = 10.0) -> str:
    """
    Non-wake-word single listen — used when JARVIS is already mid-conversation.
    """
    try:
        audio = _record_until_silence(
            max_duration=timeout,
            wait_for_speech_timeout=timeout,
        )
        return transcribe(audio)
    except Exception as exc:
        logger.error("listen_once error: %s", exc)
        return ""


# ── Background continuous listener ────────────────────────────────────────────

class WakeWordListener(threading.Thread):
    """
    Daemon thread that monitors the microphone continuously.
    Calls `callback(command_text)` each time a wake word + command is captured.
    """

    def __init__(self, callback: Callable[[str], None]):
        super().__init__(daemon=True, name="WakeWordListener")
        self.callback = callback
        self._stop_event = threading.Event()
        # Preload Whisper on main thread to prevent PyTorch deadlock in daemon thread.
        _get_whisper()

    def run(self) -> None:
        from core.speaker import speak
        logger.info("WakeWordListener thread started.")

        while not self._stop_event.is_set():
            try:
                inline_command = _wait_for_wake_word()

                if inline_command:
                    first_cmd = inline_command
                else:
                    speak("Yes, Sir?")
                    logger.info("Entering conversation mode...")
                    first_cmd = _listen_for_next_command(idle_timeout=_FIRST_COMMAND_TIMEOUT)

                if not first_cmd:
                    continue

                logger.info("User command captured: '%s'", first_cmd)
                self.callback(first_cmd)

                logger.info(
                    "Conversation mode active — listening for %.0fs of silence to exit.",
                    CONVERSATION_IDLE_TIMEOUT,
                )
                while not self._stop_event.is_set():
                    cmd = _listen_for_next_command(idle_timeout=CONVERSATION_IDLE_TIMEOUT)
                    if cmd is None:
                        logger.info("Conversation idle — returning to passive wake-word mode.")
                        break
                    # Filter out bare wake-word-only utterances in conversation mode
                    for ww in WAKE_WORDS:
                        if cmd.lower() == ww:
                            cmd = ""
                            break
                    if not cmd:
                        continue
                    logger.info("User command captured: '%s'", cmd)
                    self.callback(cmd)

            except Exception as exc:
                logger.error("WakeWordListener loop error: %s", exc)
                time.sleep(1)

    def stop(self) -> None:
        self._stop_event.set()