"""
core/speaker.py — TTS output for J.A.R.V.I.S. using edge-tts (Microsoft Edge, free).

Voice: en-GB-RyanNeural — closest freely available voice to MCU JARVIS.

Architecture (upgraded with Priority Min-Heap Speech Queue):
  ─────────────────────────────────────────────────────────────────
  All speech requests → SpeechQueue (priority heap)
                            │
                       Consumer thread
                            │
                    _speak_async() [one at a time]
  ─────────────────────────────────────────────────────────────────

  Priority levels:
    PRIORITY_CHAT    = 1  — User-facing chat responses (highest priority)
    PRIORITY_ALERT   = 2  — Due reminders / calendar alerts
    PRIORITY_MONITOR = 3  — Passive system resource warnings (lowest priority)

  Benefits:
    • JARVIS never talks over himself
    • If a CPU warning fires while speaking, it waits politely
    • Reminders always beat passive alerts
    • speak() blocks until the audio is played (preserves synchronous feel)
    • speak_async_fire() fires at PRIORITY_ALERT and returns immediately
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
import queue
import re
import sys
import threading
import tempfile
from typing import Optional

import edge_tts  # type: ignore

from config import TTS_VOICE, TTS_RATE, TTS_VOLUME, USER_NAME, USER_NAME_PHONETIC

logger = logging.getLogger(__name__)

# Flag that allows non-async callers to suppress speech (e.g., testing)
_muted: bool = False


# ── Priority levels ───────────────────────────────────────────────────────────

PRIORITY_CHAT    = 1   # Direct user replies — highest priority
PRIORITY_ALERT   = 2   # Reminders / calendar events
PRIORITY_MONITOR = 3   # CPU / battery / passive system warnings


def set_muted(muted: bool) -> None:
    global _muted
    _muted = muted


# ── Hindi / Hinglish detection ────────────────────────────────────────────────

def _is_hindi_or_hinglish(text: str) -> bool:
    """Detect if the text contains Devanagari script or clear Hinglish words.
    Threshold is 3+ Hinglish-specific words to avoid false positives on English.
    """
    # Check for Devanagari characters — definitive signal
    if any('\u0900' <= char <= '\u097f' for char in text):
        return True

    # Only include words that are unambiguously Hinglish (NOT short English words)
    hinglish_words = {
        "kya", "haan", "nahin", "nhi", "achha", "accha", "thik", "theek",
        "kar", "karo", "rha", "raha", "rhi", "rahi", "gaya", "gye",
        "aaj", "kal", "kaise", "kaisey", "tum", "aap", "mera", "meri", "hum",
        "hoga", "shukriya", "bhai", "yaar", "kuch", "hota",
        "tumhara", "apka", "kaisa", "rahe", "khole", "kholo", "chalao",
        "badhao", "sunao", "batao", "bolo", "dikhao", "awaaz", "abhi",
        "zaroor", "bilkul", "theek hai", "bas", "phir", "pehle",
    }
    words = set(re.findall(r'\b\w+\b', text.lower()))
    intersection = words.intersection(hinglish_words)
    # Require at least 3 clear Hinglish words to switch voice
    if len(intersection) >= 3:
        return True
    return False


# ── Core async TTS ────────────────────────────────────────────────────────────

async def _speak_async(text: str) -> None:
    """
    Core async coroutine:
      1. Use edge-tts to synthesize text → temp MP3 file.
      2. Play the file using playsound or fallback to pygame.
      3. Clean up the temp file.
    """
    if not text or _muted:
        return

    # Sanitise — remove markdown formatting that sounds awful when spoken
    clean = (
        text.replace("**", "")
            .replace("*", "")
            .replace("#", "")
            .replace("`", "")
            .replace("J.A.R.V.I.S.", "Jarvis")
            .replace(USER_NAME, USER_NAME_PHONETIC)
            .strip()
    )
    if not clean:
        return

    tmp_path: Optional[str] = None
    try:
        voice_to_use = "hi-IN-MadhurNeural" if _is_hindi_or_hinglish(clean) else TTS_VOICE
        logger.info("TTS Output Voice Selected: %s", voice_to_use)
        communicate = edge_tts.Communicate(clean, voice=voice_to_use, rate=TTS_RATE, volume=TTS_VOLUME)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        await communicate.save(tmp_path)
        _play_audio(tmp_path)

    except Exception as exc:
        logger.error("TTS error: %s", exc)
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _play_audio(path: str) -> None:
    """
    Play an audio file. Tries:
      1. playsound (cross-platform, simple)
      2. pygame mixer
      3. os.startfile (Windows only)
    """
    # ── Option 1: playsound ───────────────────────────────────────────────────
    try:
        from playsound import playsound  # type: ignore
        playsound(path)
        return
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("playsound failed: %s", exc)

    # ── Option 2: pygame ──────────────────────────────────────────────────────
    try:
        import pygame  # type: ignore
        pygame.mixer.init()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pass
        pygame.mixer.quit()
        return
    except Exception as exc:
        logger.debug("pygame playback failed: %s", exc)

    # ── Option 3: Windows fallback ────────────────────────────────────────────
    try:
        import time
        os.startfile(path)
        time.sleep(3)
        return
    except Exception as exc:
        logger.error("All playback methods failed: %s", exc)


def _run_tts_in_thread(text: str) -> None:
    """Run a single TTS coroutine synchronously in a fresh event loop."""
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_speak_async(text))
    except Exception as exc:
        logger.error("TTS thread error: %s", exc)
    finally:
        loop.close()


# ── Priority Speech Queue (Min-Heap) ──────────────────────────────────────────

class _SpeechQueue:
    """
    Thread-safe priority speech queue backed by Python's heapq-based PriorityQueue.

    Each item is a tuple: (priority, sequence_number, text, done_event)
      • priority        — lower = higher priority (1=chat, 2=alert, 3=monitor)
      • sequence_number — tiebreaker so equal-priority items play FIFO
      • text            — the string to speak
      • done_event      — threading.Event set when this item finishes playing
                          (None for fire-and-forget items)

    One background consumer thread pulls items one-at-a-time and plays them.
    The thread is started lazily on first use and lives until process exit.
    """

    def __init__(self) -> None:
        self._q: queue.PriorityQueue = queue.PriorityQueue()
        self._counter = itertools.count()   # monotonic tiebreaker
        self._consumer: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _ensure_consumer(self) -> None:
        """Start the consumer thread if it is not already running."""
        with self._lock:
            if self._consumer is None or not self._consumer.is_alive():
                self._consumer = threading.Thread(
                    target=self._consumer_loop,
                    daemon=True,
                    name="JARVIS-TTS-Queue",
                )
                self._consumer.start()
                logger.debug("SpeechQueue consumer thread started.")

    def _consumer_loop(self) -> None:
        """Background thread: pop items from the heap and play them one-by-one."""
        while True:
            try:
                priority, seq, text, done_event = self._q.get(block=True)
                logger.debug(
                    "SpeechQueue dequeued (priority=%d, seq=%d): '%s'",
                    priority, seq, text[:60],
                )
                try:
                    from ui.ws_bridge import ui_bridge
                    ui_bridge.update_state("SPEAKING")
                    if priority in (1, 2):
                        ui_bridge.add_transcript("JARVIS", text)
                except Exception:
                    pass

                _run_tts_in_thread(text)
            except Exception as exc:
                logger.error("SpeechQueue consumer error: %s", exc)
            finally:
                if done_event is not None:
                    done_event.set()
                try:
                    self._q.task_done()
                except Exception:
                    pass
                if self._q.empty():
                    try:
                        from ui.ws_bridge import ui_bridge
                        ui_bridge.update_state("IDLE")
                    except Exception:
                        pass

    def enqueue(
        self,
        text: str,
        priority: int = PRIORITY_CHAT,
        block: bool = True,
    ) -> None:
        """
        Add text to the speech queue.

        Args:
            text:     The string to speak.
            priority: Lower = higher priority (use module-level constants).
            block:    If True, block until audio has finished playing.
                      If False, return immediately (fire-and-forget).
        """
        if not text or _muted:
            return

        self._ensure_consumer()

        done_event: Optional[threading.Event] = threading.Event() if block else None
        seq = next(self._counter)

        safe = f"\nJARVIS: {text}\n"
        print(
            safe.encode(sys.stdout.encoding or "utf-8", errors="replace")
               .decode(sys.stdout.encoding or "utf-8", errors="replace")
        )
        logger.info("SpeechQueue enqueue (priority=%d): %s", priority, text[:120])

        self._q.put((priority, seq, text, done_event))

        if block and done_event is not None:
            done_event.wait()   # Block caller until this item is done playing


# Module-level singleton
_SPEECH_QUEUE = _SpeechQueue()


# ── Public API ────────────────────────────────────────────────────────────────

def speak(text: str, priority: int = PRIORITY_CHAT) -> None:
    """
    Speak text with the given priority.
    Blocks until the audio finishes playing.

    Priority 1 (PRIORITY_CHAT)    — direct user chat replies
    Priority 2 (PRIORITY_ALERT)   — reminders / calendar alerts
    Priority 3 (PRIORITY_MONITOR) — proactive system warnings
    """
    _SPEECH_QUEUE.enqueue(text, priority=priority, block=True)


def speak_async_fire(text: str, priority: int = PRIORITY_ALERT) -> None:
    """
    Non-blocking fire-and-forget TTS for proactive alerts.
    The item is queued behind any currently-playing speech and plays when ready.
    Defaults to PRIORITY_ALERT (2) so it beats passive monitor warnings.
    """
    _SPEECH_QUEUE.enqueue(text, priority=priority, block=False)
