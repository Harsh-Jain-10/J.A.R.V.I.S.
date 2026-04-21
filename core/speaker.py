"""
core/speaker.py — TTS output for J.A.R.V.I.S. using edge-tts (Microsoft Edge, free).

Voice: en-GB-RyanNeural — closest freely available voice to MCU JARVIS.
Playback is fully async so JARVIS can speak without blocking the main loop.
"""

import asyncio
import logging
import os
import sys
import threading
import tempfile
from typing import Optional

import edge_tts  # type: ignore

from config import TTS_VOICE, TTS_RATE, TTS_VOLUME, USER_NAME, USER_NAME_PHONETIC

logger = logging.getLogger(__name__)

# Flag that allows non-async callers to suppress speech (e.g., testing)
_muted: bool = False


def set_muted(muted: bool) -> None:
    global _muted
    _muted = muted


async def _speak_async(text: str) -> None:
    """
    Core async coroutine:
      1. Use edge-tts to synthesize text → temp MP3 file.
      2. Play the file using playsound or fallback to os.startfile.
      3. Clean up the temp file.
    """
    if not text or _muted:
        return

    # Sanitise — remove markdown-style formatting that sounds awful when spoken
    # Also substitute the written name with the phonetic name for TTS
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

    tmp_path = None   # FIX Bug 4: guard against NameError in finally if TTS fails before tempfile is created
    try:
        communicate = edge_tts.Communicate(clean, voice=TTS_VOICE, rate=TTS_RATE, volume=TTS_VOLUME)

        # Write to a temp file
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        await communicate.save(tmp_path)

        # ── Playback ──────────────────────────────────────────────────────────
        _play_audio(tmp_path)

    except Exception as exc:
        logger.error("TTS error: %s", exc)
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):  # FIX Bug 4: 'tmp_path and' guards against NameError
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
        time.sleep(3)   # crude wait — length unknown
        return
    except Exception as exc:
        logger.error("All playback methods failed: %s", exc)


def speak(text: str) -> None:
    """
    Thread-safe synchronous wrapper.
    Runs the async TTS pipeline in its own event loop so it can be called
    from any thread (including non-async contexts like APScheduler jobs).
    """
    logger.info("JARVIS says: %s", text[:120])
    safe_text = f"\nJARVIS: {text}\n"
    print(safe_text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8", errors="replace"))

    def _run():
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(_speak_async(text))
        except Exception as exc:
            logger.error("speak() thread error: %s", exc)
        finally:
            loop.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join()  # block until audio is done so responses don't pile up


def speak_async_fire(text: str) -> None:
    """
    Non-blocking fire-and-forget variant for proactive alerts,
    so they don't stall the main thread.
    """
    def _run():
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(_speak_async(text))
        except Exception as exc:
            logger.error("speak_async_fire error: %s", exc)
        finally:
            loop.close()

    t = threading.Thread(target=_run, daemon=True, name="TTS-FireForget")
    t.start()
