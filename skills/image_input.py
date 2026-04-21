"""
skills/image_input.py — Multimodal image analysis skill for J.A.R.V.I.S.

Sends images to Gemini Vision (gemini-1.5-flash, free tier).
"""

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def _extract_image_path(query: str) -> str:
    """Extract a file path from the query string."""
    # Windows absolute path
    match = re.search(r"[A-Za-z]:\\[^\s\"']+", query)
    if match:
        return match.group(0)
    # Unix path
    match = re.search(r"/[^\s\"']+", query)
    if match:
        return match.group(0)
    # Relative path with image extension
    match = re.search(r"[\w./\\-]+\.(png|jpg|jpeg|bmp|gif|webp)", query, re.IGNORECASE)
    if match:
        return match.group(0)
    return ""


def handle(query: str, brain=None) -> str:
    if brain is None:
        return "Image analysis requires the brain module, Sir."

    image_path = _extract_image_path(query)

    if not image_path:
        return (
            "Please provide an image file path, Sir. "
            "For example: 'analyze image C:\\Users\\Me\\photo.jpg'"
        )

    if not os.path.exists(image_path):
        return f"I cannot find an image at '{image_path}', Sir. Please verify the path."

    # Extract the question (everything that's not the path)
    question = query.replace(image_path, "").strip()
    for trigger in ["analyze image", "analyse image", "look at", "describe", "what is in"]:
        question = question.replace(trigger, "").strip()

    if not question:
        question = "Please describe this image in detail."

    logger.info("Analyzing image: %s", image_path)
    return brain.analyze_image(image_path, question)
