"""
core/listener.py — Wake-word detection + Multimodal STT for J.A.R.V.I.S.
"""

import collections
import io
import json
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
    GROQ_API_KEY,
    GEMINI_API_KEY,
    GEMINI_MODEL,
)

logger = logging.getLogger(__name__)

# ── Audio constants ───────────────────────────────────────────────────────────
SAMPLE_RATE = 16000   # Whisper and Gemini expect 16 kHz
CHANNELS = 1
DTYPE = "int16"

# ── Threshold constants ───────────────────────────────────────────────────────
# These are calibrated dynamically on startup, but have safe fallbacks.
SPEECH_START_THRESHOLD: int = 300
SILENCE_END_THRESHOLD: int = 150

_WHISPER_INITIAL_PROMPT = (
    "JARVIS voice assistant commands: take a screenshot, open notepad, "
    "what is the weather, search for, remind me to, system info, "
    "set volume, open chrome, open calculator, play music, "
    "what time is it, lock the screen, close the app."
)

# ── Shared Global State for Vocal Emotion and Response ────────────────────────
LATEST_EMOTION: Optional[str] = None
LATEST_GEMINI_RESPONSE: Optional[str] = None

# ── Cloud STT clients ─────────────────────────────────────────────────────────
_groq_client_stt = None
if GROQ_API_KEY:
    try:
        from groq import Groq  # type: ignore
        _groq_client_stt = Groq(api_key=GROQ_API_KEY)
        logger.info("Groq STT client initialised.")
    except Exception as exc:
        logger.warning("Could not load Groq STT: %s", exc)

_genai_client_stt = None
if GEMINI_API_KEY:
    try:
        from google import genai  # type: ignore
        _genai_client_stt = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Gemini STT client initialised.")
    except Exception as exc:
        logger.warning("Could not load Gemini STT: %s", exc)

# ── Lazy-load Whisper fallback ───────────────────────────────────────────────
_whisper_model = None
_whisper_lock = threading.Lock()

def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        with _whisper_lock:
            if _whisper_model is None:
                try:
                    import whisper  # type: ignore
                    logger.info("Cloud STT services unavailable. Loading local Whisper model '%s' as fallback...", WHISPER_MODEL)
                    _whisper_model = whisper.load_model(WHISPER_MODEL)
                    logger.info("Local Whisper model loaded.")
                except Exception as exc:
                    logger.error("Could not load local Whisper: %s", exc)
                    _whisper_model = None
    return _whisper_model

# ── SpeechRecognition recognizer (for Google STT fallback) ───────────────────
_recognizer = sr.Recognizer()
_recognizer.energy_threshold = MIC_ENERGY_THRESHOLD
_recognizer.dynamic_energy_threshold = True
_recognizer.pause_threshold = 0.6

# ── Audio capture helpers ─────────────────────────────────────────────────────

def _record_audio(duration: float) -> np.ndarray:
    """Record *duration* seconds of audio from the default input device at 16 kHz."""
    frames = int(SAMPLE_RATE * duration)
    audio = sd.rec(frames, samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE)
    sd.wait()
    return audio.flatten()

def _numpy_to_audio_data(audio_np: np.ndarray) -> sr.AudioData:
    """Convert a numpy int16 array to a SpeechRecognition AudioData object."""
    raw_bytes = audio_np.tobytes()
    return sr.AudioData(raw_bytes, SAMPLE_RATE, 2)

def numpy_to_wav_bytes(audio_np: np.ndarray) -> bytes:
    """Convert a numpy int16 array to a WAV file in memory."""
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(audio_np.tobytes())
    return wav_io.getvalue()

def calibrate_threshold_with_stream(stream: sd.InputStream, duration: float = 1.2) -> None:
    """Calibrate speech thresholds based on ambient noise of the active stream.
    
    NOTE: Windows audio drivers often return RMS=0 for the first ~500ms after
    the stream opens (driver warm-up latency). We discard that initial window
    before measuring noise to avoid setting thresholds of 0 or near-0.
    """
    global SPEECH_START_THRESHOLD, SILENCE_END_THRESHOLD
    print("\n⚙  Calibrating microphone — please stay silent for a moment...", flush=True)
    logger.info("Calibrating microphone for %.1fs... Please remain silent.", duration)
    try:
        chunk_size = int(SAMPLE_RATE * 0.1)  # 100ms chunks

        # ── Step 1: Discard first 500ms (Windows driver warm-up) ─────────────
        warmup_chunks = 5  # 5 × 100ms = 500ms
        for _ in range(warmup_chunks):
            stream.read(chunk_size)

        # ── Step 2: Collect actual calibration audio ──────────────────────────
        frames_needed = int(SAMPLE_RATE * duration)
        chunks = []
        read_frames = 0
        while read_frames < frames_needed:
            chunk, _ = stream.read(chunk_size)
            chunks.append(chunk.flatten())
            read_frames += len(chunk)
        
        noise = np.concatenate(chunks)
        rms_values = []
        for i in range(0, len(noise), chunk_size):
            c = noise[i:i+chunk_size]
            if len(c) < chunk_size:
                continue
            rms = int(np.sqrt(np.mean(c.astype(np.float32) ** 2)))
            if rms > 0:  # Skip any remaining zero-RMS chunks
                rms_values.append(rms)
        
        if rms_values:
            max_rms = max(rms_values)
            avg_rms = int(sum(rms_values) / len(rms_values))
        else:
            max_rms, avg_rms = 50, 30
        
        # ── Step 3: Set thresholds with hard floors ───────────────────────────
        raw_start = int(max(max_rms * 1.8, max_rms + 80))
        SPEECH_START_THRESHOLD = max(250, min(raw_start, 800))  # Floor=250, Cap=800
        SILENCE_END_THRESHOLD  = max(125, int(SPEECH_START_THRESHOLD * 0.5))  # Floor=125
        
        print(
            f"✅ Calibration done — noise floor: avg={avg_rms} max={max_rms} | "
            f"speech threshold={SPEECH_START_THRESHOLD} silence threshold={SILENCE_END_THRESHOLD}",
            flush=True
        )
        logger.info(
            "Calibration complete. Ambient noise: Avg RMS=%d, Max RMS=%d. "
            "Set SPEECH_START_THRESHOLD=%d, SILENCE_END_THRESHOLD=%d",
            avg_rms, max_rms, SPEECH_START_THRESHOLD, SILENCE_END_THRESHOLD
        )
    except Exception as e:
        logger.warning("Microphone calibration failed: %s. Using default threshold 300.", e)
        print(f"⚠  Calibration failed ({e}). Using safe defaults.", flush=True)

def _read_from_stream(
    active_stream: sd.InputStream,
    max_duration: float,
    silence_duration: float,
    wait_for_speech_timeout: Optional[float]
) -> np.ndarray:
    """Read chunks from active sounddevice InputStream until silence or timeout."""
    chunk_size = int(SAMPLE_RATE * 0.1)  # 100ms chunks
    max_chunks = int(max_duration / 0.1)
    silence_chunks_needed = int(silence_duration / 0.1)
    wait_chunks_max = (
        int(wait_for_speech_timeout / 0.1)
        if wait_for_speech_timeout is not None
        else None
    )

    pre_buffer_chunks = 5
    pre_buffer = collections.deque(maxlen=pre_buffer_chunks)

    frames: list[np.ndarray] = []
    has_spoken = False
    silent_chunks = 0
    waited_chunks = 0

    while True:
        chunk, _ = active_stream.read(chunk_size)
        chunk = chunk.flatten()
        rms = int(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))

        if not has_spoken:
            waited_chunks += 1
            if rms >= SPEECH_START_THRESHOLD:
                has_spoken = True
                frames.extend(pre_buffer)
                frames.append(chunk)
            elif wait_chunks_max is not None and waited_chunks >= wait_chunks_max:
                logger.debug("No speech detected within timeout — returning empty audio.")
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

def _record_until_silence(
    max_duration: float = 15.0,
    silence_duration: float = 0.6,
    wait_for_speech_timeout: Optional[float] = None,
    stream: Optional[sd.InputStream] = None,
) -> np.ndarray:
    """Record audio until silence is detected, reusing stream if available."""
    if stream is not None:
        try:
            stream.stop()
            stream.start()
        except Exception as e:
            logger.debug("Failed to stop/start stream: %s", e)
        return _read_from_stream(stream, max_duration, silence_duration, wait_for_speech_timeout)
    else:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE) as temp_stream:
            return _read_from_stream(temp_stream, max_duration, silence_duration, wait_for_speech_timeout)

# ── Text post-processor ───────────────────────────────────────────────────────

_HALLUCINATION_PATTERNS = [
    r"^\s*\d+\s+",           # Leading digits
    r"^[\.\,\!\?\-\s]+",     # Leading punctuation
    r"[\.\,\!\?]+$",         # Trailing punctuation
    r"\bthank you\.?\s*$",   # Hallucinations
    r"\bbye\.?\s*$",
    r"\bsubs by.*$",
    r"\bsubtitles by.*$",
]

_HALLUCINATION_RE = [re.compile(p, re.IGNORECASE) for p in _HALLUCINATION_PATTERNS]

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
    """Clean Whisper output transcript."""
    cleaned = text.strip()
    for pattern in _HALLUCINATION_RE:
        cleaned = pattern.sub("", cleaned).strip()

    lower = cleaned.lower()
    for two_word, one_word in _WORD_JOIN_MAP.items():
        lower = lower.replace(two_word, one_word)
    cleaned = lower

    return cleaned.strip()

# ── Transcription Methods ─────────────────────────────────────────────────────

_MIN_AUDIO_SAMPLES = int(SAMPLE_RATE * 0.4)

def _transcribe_groq(audio_np: np.ndarray) -> Optional[str]:
    """Transcribe using Groq Cloud STT (whisper-large-v3) in ~200ms.
    
    NOTE: language is NOT forced to 'en' so Groq can auto-detect Hindi/Hinglish.
    The transcript is passed through as-is (may be in Hindi Devanagari or Hinglish).
    """
    if _groq_client_stt is None:
        return None
    try:
        wav_bytes = numpy_to_wav_bytes(audio_np)
        response = _groq_client_stt.audio.transcriptions.create(
            file=("speech.wav", wav_bytes, "audio/wav"),
            model="whisper-large-v3",
            # No 'language' param — let Whisper auto-detect Hindi/Hinglish/English
            prompt=_WHISPER_INITIAL_PROMPT,
        )
        text = response.text.strip()
        logger.debug("Groq STT transcript: '%s'", text)
        return _clean_transcript(text) or None
    except Exception as exc:
        logger.warning("Groq STT failed: %s", exc)
        return None

def _transcribe_multimodal_gemini(audio_np: np.ndarray) -> Optional[tuple[str, str, str]]:
    """Send audio to Gemini Flash for transcript, emotion, and a pre-computed response.
    
    Response language policy:
      • JARVIS ALWAYS responds in English regardless of what language the user spoke.
      • The transcript may be in any language (Hindi, English, Hinglish).
      • Emotion is detected from vocal tone, not language.
    """
    if _genai_client_stt is None:
        return None
    try:
        from google.genai import types as genai_types
        wav_bytes = numpy_to_wav_bytes(audio_np)

        from datetime import datetime
        now = datetime.now()
        date_str = now.strftime("%A, %d %B %Y")
        time_str = now.strftime("%I:%M %p")

        prompt = (
            "You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), the AI assistant. "
            "Analyze the user's voice in the provided audio file and respond with a JSON object.\n\n"
            "Tasks:\n"
            "1. TRANSCRIBE exactly what the user said (preserve their original language — Hindi, Hinglish, or English).\n"
            "2. DETECT their vocal emotion from pitch, tone, volume, speed, and pauses. "
            "(e.g. angry, sad, happy, excited, hesitant, calm, frustrated, tired)\n"
            "3. FORMULATE a response as JARVIS — formal, witty, British, calling the user 'Sir'.\n\n"
            "CRITICAL LANGUAGE RULE: You MUST ALWAYS write the 'response' field in ENGLISH ONLY. "
            "Never respond in Hindi, Hinglish, or any other language — even if the user spoke Hindi. "
            "Understand the user's Hindi/Hinglish input, but reply exclusively in English.\n\n"
            f"[SYSTEM CONTEXT — Current Date: {date_str} | Current Time (IST): {time_str}]\n\n"
            "Respond ONLY with a JSON object with exactly these keys: "
            "{'transcript': string, 'emotion': string, 'response': string}"
        )

        response = _genai_client_stt.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                genai_types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                prompt
            ],
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )

        result_text = response.text.strip()
        data = json.loads(result_text)
        transcript = data.get("transcript", "").strip()
        emotion = data.get("emotion", "calm").strip()
        jarvis_response = data.get("response", "").strip()

        logger.info("Gemini Multimodal: Emotion: '%s'", emotion)
        return transcript, emotion, jarvis_response
    except Exception as exc:
        logger.warning("Gemini Multimodal STT failed: %s", exc)
        return None

def _transcribe_gemini_fallback(audio_np: np.ndarray) -> Optional[str]:
    """Transcribe using Gemini 2.0 Flash basic audio input fallback."""
    if _genai_client_stt is None:
        return None
    try:
        from google.genai import types as genai_types
        wav_bytes = numpy_to_wav_bytes(audio_np)
        response = _genai_client_stt.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                genai_types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                "Transcribe this audio clip exactly. Return only the transcription, no comments."
            ]
        )
        text = response.text.strip()
        return _clean_transcript(text) or None
    except Exception as exc:
        logger.warning("Gemini fallback STT failed: %s", exc)
        return None

def _transcribe_whisper(audio_np: np.ndarray) -> Optional[str]:
    """Transcribe using local Whisper model fallback."""
    if len(audio_np) < _MIN_AUDIO_SAMPLES:
        return None
    model = _get_whisper()
    if model is None:
        return None
    try:
        float_audio = audio_np.astype(np.float32) / 32768.0
        result = model.transcribe(
            float_audio,
            fp16=False,
            language="en",
            initial_prompt=_WHISPER_INITIAL_PROMPT,
        )
        raw_text = result.get("text", "").strip()
        return _clean_transcript(raw_text) or None
    except Exception as exc:
        logger.error("Whisper local transcription error: %s", exc)
        return None

def _transcribe_google(audio_np: np.ndarray) -> Optional[str]:
    """Transcribe using Google Speech Recognition fallback."""
    if len(audio_np) < _MIN_AUDIO_SAMPLES:
        return None
    try:
        audio_data = _numpy_to_audio_data(audio_np)
        text = _recognizer.recognize_google(audio_data)
        return _clean_transcript(text) or None
    except Exception as exc:
        logger.debug("Google STT failed: %s", exc)
        return None

def transcribe(audio_np: np.ndarray) -> str:
    """Unified STT pipeline — Groq first (fast), Gemini enhancement second.

    Order:
      1. Groq Cloud STT  — whisper-large-v3, ~200ms, very reliable
      2. Gemini Multimodal (async enrichment) — adds emotion + pre-response
         Only attempted after Groq succeeds, in a non-blocking best-effort way.
      3. Gemini fallback STT   — if Groq failed
      4. Local Whisper model   — offline fallback
      5. Google Web STT        — last resort
    """
    global LATEST_EMOTION, LATEST_GEMINI_RESPONSE
    LATEST_EMOTION = None
    LATEST_GEMINI_RESPONSE = None

    if len(audio_np) < _MIN_AUDIO_SAMPLES:
        return ""

    print("⚙  Processing your command...", flush=True)

    # ── 1. Groq Cloud STT (primary — fast and reliable) ──────────────────────
    groq_text = ""
    if _groq_client_stt is not None:
        groq_text = _transcribe_groq(audio_np) or ""

    if groq_text:
        return groq_text

    # ── 3. Gemini Multimodal STT (if Groq unavailable / failed) ─────────────
    if _genai_client_stt is not None:
        result = _transcribe_multimodal_gemini(audio_np)
        if result:
            transcript, emotion, response = result
            LATEST_EMOTION = emotion
            LATEST_GEMINI_RESPONSE = response
            return transcript

    # ── 4. Gemini basic fallback ─────────────────────────────────────────────
    if _genai_client_stt is not None:
        text = _transcribe_gemini_fallback(audio_np)
        if text:
            return text

    # ── 5. Local Whisper (offline) ───────────────────────────────────────────
    text = _transcribe_whisper(audio_np)
    if text:
        return text

    # ── 6. Google Web STT (last resort) ─────────────────────────────────────
    text = _transcribe_google(audio_np)
    return text or ""

# ── Public API ────────────────────────────────────────────────────────────────

CONVERSATION_IDLE_TIMEOUT: float = 20.0
_FIRST_COMMAND_TIMEOUT: float = 6.0

def _wait_for_wake_word(stream: Optional[sd.InputStream] = None) -> str:
    """Passive mode: wait for wake word and return trailing inline command."""
    logger.info("JARVIS in passive mode — waiting for wake word: %s", WAKE_WORDS)
    print("\n🎤  [PASSIVE] Waiting for wake word (say 'Hey JARVIS' or 'JARVIS')...", flush=True)
    while True:
        try:
            audio = _record_until_silence(wait_for_speech_timeout=None, stream=stream)
            if len(audio) == 0:
                continue

            text = transcribe(audio)
            if not text:
                continue

            lowered = text.lower().strip()

            # ── Strict wake-word check: phrase must CONTAIN a wake word ────────
            # Reject bare non-command phrases like "are you listening"
            wake_word_found = False
            for ww in WAKE_WORDS:
                if ww in lowered:
                    wake_word_found = True
                    idx = lowered.find(ww)
                    command_text = text[idx + len(ww):].strip(" .,!?")
                    logger.info("Wake word '%s' detected. Inline command: '%s'", ww, command_text)
                    print(f"\n✅  Wake word detected! Command: '{command_text or '(none — will prompt)'}'", flush=True)
                    return command_text

            if not wake_word_found:
                logger.debug("Heard '%s' but no wake word — ignoring.", text)

        except Exception as exc:
            logger.error("_wait_for_wake_word error: %s", exc)
            time.sleep(0.5)

def _listen_for_next_command(
    idle_timeout: float = CONVERSATION_IDLE_TIMEOUT,
    stream: Optional[sd.InputStream] = None,
) -> Optional[str]:
    """Active conversation mode: listen directly for command."""
    try:
        from ui.ws_bridge import ui_bridge
        ui_bridge.update_state("LISTENING")
    except Exception:
        pass
    print("\n🎤  [LISTENING] Speak your command now...", flush=True)
    audio = _record_until_silence(
        max_duration=15.0,
        wait_for_speech_timeout=idle_timeout,
        stream=stream,
    )
    if len(audio) == 0:
        print("   (No speech detected — returning to passive mode)", flush=True)
        return None

    text = transcribe(audio).strip(" .,!?")
    if text:
        print(f"   You said: '{text}'", flush=True)
    return text if text else None

def listen_for_command() -> str:
    """Main entry point for command recording (single-use wrapper)."""
    from core.speaker import speak
    inline_command = _wait_for_wake_word()

    if inline_command:
        return inline_command

    speak("Yes, Sir?")
    first_cmd = _listen_for_next_command(idle_timeout=_FIRST_COMMAND_TIMEOUT)
    if first_cmd:
        return first_cmd

    return listen_for_command()

def listen_once(timeout: float = 10.0) -> str:
    """Non-wake-word single listen — used when JARVIS is already mid-conversation."""
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
    """Daemon thread that monitors the microphone continuously."""

    def __init__(self, callback: Callable[[str], None]):
        super().__init__(daemon=True, name="WakeWordListener")
        self.callback = callback
        self._stop_event = threading.Event()
        # Removed local Whisper preloading to make startup instant.

    def run(self) -> None:
        from core.speaker import speak
        logger.info("WakeWordListener thread started.")
        print("\n" + "═"*60, flush=True)
        print("  J.A.R.V.I.S. ONLINE — Initialising audio pipeline...", flush=True)
        print("═"*60 + "\n", flush=True)

        # Single persistent input stream opened once and reused
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE) as stream:
            # Calibrate threshold on startup (discards first 500ms for Windows)
            calibrate_threshold_with_stream(stream)

            print("\n" + "═"*60, flush=True)
            print("  ✅  JARVIS READY — Say 'Hey JARVIS' or 'JARVIS' to begin", flush=True)
            print("═"*60 + "\n", flush=True)

            while not self._stop_event.is_set():
                try:
                    # Pass the persistent stream to avoid open/close latency
                    inline_command = _wait_for_wake_word(stream=stream)

                    if inline_command:
                        first_cmd = inline_command
                    else:
                        print("\n🔊  [SPEAKING] Responding...", flush=True)
                        speak("Yes, Sir?")
                        logger.info("Entering conversation mode...")
                        first_cmd = _listen_for_next_command(
                            idle_timeout=_FIRST_COMMAND_TIMEOUT,
                            stream=stream
                        )

                    if not first_cmd:
                        continue

                    print(f"\n🧠  [PROCESSING] Intent: '{first_cmd}'", flush=True)
                    self.callback(first_cmd)

                    logger.info(
                        "Conversation mode active — listening for %.0fs of silence to exit.",
                        CONVERSATION_IDLE_TIMEOUT,
                    )
                    while not self._stop_event.is_set():
                        cmd = _listen_for_next_command(
                            idle_timeout=CONVERSATION_IDLE_TIMEOUT,
                            stream=stream
                        )
                        if cmd is None:
                            logger.info("Conversation idle — returning to passive wake-word mode.")
                            print("\n💤  Conversation ended — back to passive listening.", flush=True)
                            break
                            
                        # Filter out bare wake-word-only utterances
                        stripped_cmd = cmd.lower().strip()
                        is_bare_wakeword = any(stripped_cmd == ww for ww in WAKE_WORDS)
                        if is_bare_wakeword:
                            logger.debug("Ignoring bare wake-word utterance: '%s'", cmd)
                            continue
                        if not cmd.strip():
                            continue

                        print(f"\n🧠  [PROCESSING] Command: '{cmd}'", flush=True)
                        self.callback(cmd)

                except Exception as exc:
                    logger.error("WakeWordListener loop error: %s", exc)
                    time.sleep(1)

    def stop(self) -> None:
        self._stop_event.set()