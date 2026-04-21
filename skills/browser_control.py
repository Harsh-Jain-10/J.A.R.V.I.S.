"""
skills/browser_control.py — Browser & clipboard skill for J.A.R.V.I.S.

Capabilities:
  • Open URLs in default browser
  • Search Google / YouTube by voice
  • Read clipboard content
  • Copy text to clipboard
"""

import logging
import webbrowser
from typing import Optional
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


def _open_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        webbrowser.open(url)
        return f"Opening {url} in your browser, Sir."
    except Exception as exc:
        logger.error("open_url error: %s", exc)
        return f"I was unable to open the URL: {exc}"


def _search_google(query: str) -> str:
    url = f"https://www.google.com/search?q={quote_plus(query)}"
    return _open_url(url)


def _search_youtube(query: str) -> str:
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    return _open_url(url)


def _read_clipboard() -> str:
    try:
        import pyperclip  # type: ignore
        content = pyperclip.paste()
        if not content:
            return "The clipboard appears to be empty, Sir."
        return f"Clipboard contents:\n{content[:500]}"
    except ImportError:
        return "The pyperclip library is not installed, Sir."
    except Exception as exc:
        return f"Failed to read clipboard: {exc}"


def _copy_to_clipboard(text: str) -> str:
    try:
        import pyperclip  # type: ignore
        pyperclip.copy(text)
        return f"Copied to clipboard, Sir: '{text[:80]}{'...' if len(text) > 80 else ''}'"
    except ImportError:
        return "The pyperclip library is not installed, Sir."
    except Exception as exc:
        return f"Failed to copy to clipboard: {exc}"


def handle(query: str, brain=None) -> str:
    lowered = query.lower()

    # ── Clipboard ─────────────────────────────────────────────────────────────
    if "clipboard" in lowered or "paste" in lowered:
        return _read_clipboard()

    if "copy" in lowered:
        # Extract text after 'copy'
        idx = lowered.index("copy") + 4
        text = query[idx:].strip().strip("\"'")
        if text:
            return _copy_to_clipboard(text)
        return "What would you like me to copy, Sir?"

    # ── YouTube ──────────────────────────────────────────────────────────────
    if "youtube" in lowered:
        for trigger in ["youtube search ", "search youtube for ", "play on youtube "]:
            if trigger in lowered:
                q = query[lowered.index(trigger) + len(trigger):].strip()
                return _search_youtube(q)
        # "open youtube" with no query
        return _open_url("https://www.youtube.com")

    # ── Google search ────────────────────────────────────────────────────────
    if "google" in lowered:
        for trigger in ["google ", "search google for ", "google search "]:
            if trigger in lowered:
                q = query[lowered.index(trigger) + len(trigger):].strip()
                return _search_google(q)
        return _open_url("https://www.google.com")

    # ── Direct URL ───────────────────────────────────────────────────────────
    import re
    url_match = re.search(r"(https?://\S+|[\w-]+\.(com|org|net|io|co|in|uk|gov)[\w/.-]*)", lowered)
    if url_match:
        return _open_url(url_match.group(0))

    # ── 'Open website' ───────────────────────────────────────────────────────
    for trigger in ["open website ", "go to ", "navigate to ", "open ", "visit ", "browse "]:
        if trigger in lowered:
            site = query[lowered.index(trigger) + len(trigger):].strip()
            return _open_url(site)

    return "Please specify a URL or search query, Sir."
