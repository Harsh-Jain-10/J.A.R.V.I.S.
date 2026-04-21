"""
core/brain.py — Multi-LLM orchestration layer for J.A.R.V.I.S.

Strategy:
  1. Try Groq (cloud, ~0.5s, very generous free tier — primary).
  2. On rate-limit (429) or failure, fall back to Google Gemini 2.0 Flash.
  3. Personality system prompt is injected into EVERY call.
  4. Memory context block is concatenated to every user message.

Why Groq?
  - Meta Llama 3.3 70B served at ~300 tokens/sec on Groq's LPU hardware.
  - Free tier: 30 req/min, 6000 req/day — far more than typical assistant use.
  - No local GPU or Ollama daemon required — zero startup delay.
"""

import logging
from typing import Optional

from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    SYSTEM_PROMPT,
)
from memory.context_manager import get_full_prompt

logger = logging.getLogger(__name__)

# ── Groq client ───────────────────────────────────────────────────────────────
_groq_client = None
if GROQ_API_KEY:
    try:
        from groq import Groq  # type: ignore
        _groq_client = Groq(api_key=GROQ_API_KEY)
        logger.info("Groq client initialised (model: %s).", GROQ_MODEL)
    except Exception as _exc:
        logger.warning("Groq client init failed: %s", _exc)
else:
    logger.warning("GROQ_API_KEY not set — Groq will not work.")

# ── Gemini client (fallback) ──────────────────────────────────────────────────
_genai_client = None
if GEMINI_API_KEY:
    try:
        from google import genai  # type: ignore
        from google.genai import types as genai_types  # type: ignore
        _genai_client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Gemini client initialised (fallback model: %s).", GEMINI_MODEL)
    except Exception as _exc:
        logger.warning("Gemini client init failed: %s", _exc)
else:
    logger.warning("GEMINI_API_KEY not set — Gemini fallback will not work.")


class Brain:
    """
    Unified LLM interface. All public methods return plain strings.

    Call chain:  Groq  →  Gemini (rate-limit / error fallback)
    """

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _try_groq(self, prompt: str, system: str = SYSTEM_PROMPT) -> Optional[str]:
        """
        Call Groq's Chat Completions API (synchronous, ~0.5s on free tier).
        Returns None only on rate-limit (429) or unrecoverable error so the
        caller can fall back to Gemini.
        """
        if _groq_client is None:
            return None
        try:
            from groq import RateLimitError  # type: ignore
            response = _groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
                max_tokens=1024,
                temperature=0.7,
            )
            text = response.choices[0].message.content
            return text.strip() if text else None
        except Exception as exc:
            exc_str = str(exc)
            # 429 rate limit — signal caller to use Gemini
            if "429" in exc_str or "rate_limit" in exc_str.lower() or "RateLimitError" in type(exc).__name__:
                logger.warning("Groq rate limit hit — switching to Gemini fallback.")
            else:
                logger.error("Groq call failed: %s", exc)
            return None

    def _try_gemini(self, prompt: str, system: str = SYSTEM_PROMPT) -> Optional[str]:
        """
        Call Gemini 2.0 Flash via the google-genai SDK.
        Used as fallback when Groq is rate-limited or unavailable.
        """
        if _genai_client is None:
            return None
        try:
            from google.genai import types as genai_types  # type: ignore
            response = _genai_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=1024,
                ),
            )
            text = response.text
            return text.strip() if text else None
        except Exception as exc:
            logger.error("Gemini call failed: %s", exc)
            return None

    # ── Public API ────────────────────────────────────────────────────────────

    def ask(self, user_message: str) -> str:
        """
        Main entry point. Memory context is automatically injected.
        Tries Groq first, falls back to Gemini on rate-limit or failure.
        """
        full_prompt = get_full_prompt(user_message)

        # ── Primary: Groq ─────────────────────────────────────────────────────
        response = self._try_groq(full_prompt)
        if response:
            logger.info("Response from Groq.")
            return response

        # ── Fallback: Gemini ──────────────────────────────────────────────────
        logger.info("Groq unavailable — falling back to Gemini.")
        response = self._try_gemini(full_prompt)
        if response:
            logger.info("Response from Gemini fallback.")
            return response

        # ── Hard fallback ──────────────────────────────────────────────────────
        return (
            "I'm afraid both my primary and fallback models are currently "
            "unreachable, Sir. Please check your API keys and internet connection."
        )

    def ask_raw(self, prompt: str) -> str:
        """
        Ask without injecting memory context. Used for meta-tasks like
        summarisation and intent classification where the prompt IS the content.
        """
        response = self._try_groq(prompt)
        if response:
            return response
        response = self._try_gemini(prompt)
        return response or ""

    def classify_intent(self, user_message: str) -> str:
        """
        Ask the LLM to classify the user's intent.
        Returns one of the valid intent labels as a plain string.
        """
        valid_labels = (
            "CHAT | WEB_SEARCH | WEATHER | NEWS | OPEN_APP | SYSTEM_CONTROL | "
            "FILE_OPS | REMINDER | BROWSER | IMAGE_ANALYSIS | MEMORY_RECALL"
        )
        prompt = (
            f"Classify the following user input into EXACTLY ONE intent label.\n\n"
            f"Valid labels: {valid_labels}\n\n"
            f"GUIDELINES:\n"
            f"- If the user asks a factual question (e.g., 'who holds', 'what is', 'when did'), use WEB_SEARCH.\n"
            f"- Only use NEWS if the user explicitly asks for 'news', 'headlines', or 'top stories'.\n"
            f"- Use MEMORY_RECALL for questions about past conversations.\n\n"
            f"User input: \"{user_message}\"\n\n"
            f"Respond with ONLY the label. No explanation. No punctuation."
        )
        return self.ask_raw(prompt) or "CHAT"

    def analyze_image(self, image_path: str, question: str = "") -> str:
        """
        Send an image to Gemini Vision (Groq does not support vision yet).
        """
        if _genai_client is None:
            return "Gemini Vision is not available, Sir. Please check your API key."

        try:
            from google.genai import types as genai_types  # type: ignore
            import PIL.Image as PILImage  # type: ignore
            img = PILImage.open(image_path)
            q = question or "Please describe this image in detail."
            response = _genai_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[q, img],
                config=genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                ),
            )
            text = response.text
            return text.strip() if text else "I was unable to analyse the image, Sir."
        except FileNotFoundError:
            return f"I cannot find the image at '{image_path}', Sir."
        except Exception as exc:
            logger.error("Image analysis error: %s", exc)
            return f"Image analysis failed: {exc}"
