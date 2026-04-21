"""
skills/web_search.py — DuckDuckGo + Wikipedia search skill for J.A.R.V.I.S.
No API key required — completely free.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _duckduckgo_search(query: str, max_results: int = 3) -> str:
    """Search DuckDuckGo and return top results as formatted text."""
    try:
        from duckduckgo_search import DDGS  # type: ignore
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))

        if not results:
            return "I found no results for that query on DuckDuckGo, Sir."

        lines = [f"Here are the top results for '{query}':"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "Unknown")
            body = r.get("body", "")[:200]
            url = r.get("href", "")
            lines.append(f"\n{i}. {title}\n   {body}\n   Source: {url}")

        return "\n".join(lines)

    except ImportError:
        logger.error("duckduckgo-search library not installed.")
        return "The DuckDuckGo search library is not available, Sir."
    except Exception as exc:
        logger.error("DuckDuckGo search error: %s", exc)
        return f"I encountered an error searching DuckDuckGo: {exc}"


def _wikipedia_search(query: str) -> str:
    """Fetch a Wikipedia summary for the query."""
    try:
        import wikipedia  # type: ignore
        wikipedia.set_lang("en")
        try:
            summary = wikipedia.summary(query, sentences=4, auto_suggest=True)
            return f"According to Wikipedia:\n{summary}"
        except wikipedia.exceptions.DisambiguationError as e:
            # Multiple results — pick the first option
            try:
                summary = wikipedia.summary(e.options[0], sentences=4)
                return f"According to Wikipedia ('{e.options[0]}'):\n{summary}"
            except Exception:
                return f"Wikipedia has multiple entries for '{query}'. Please be more specific, Sir."
        except wikipedia.exceptions.PageError:
            return f"Wikipedia has no page for '{query}', Sir."
    except ImportError:
        return "The Wikipedia library is not installed, Sir."
    except Exception as exc:
        logger.error("Wikipedia error: %s", exc)
        return f"Wikipedia lookup failed: {exc}"


def handle(query: str, brain=None) -> str:
    """
    Main entry point for WEB_SEARCH intent.
    Tries Wikipedia for knowledge-style questions, DuckDuckGo for everything else.
    If a brain is provided, it summarises the raw results.
    """
    # ── Wikipedia for factual/encyclopaedic queries ───────────────────────────
    wiki_keywords = ["who is", "what is", "history of", "biography", "define ", "explain "]
    lowered = query.lower()
    raw_result = ""

    if any(kw in lowered for kw in wiki_keywords):
        clean_query = query.lower()
        for kw in wiki_keywords:
            clean_query = clean_query.replace(kw, "").strip()
        wiki_result = _wikipedia_search(clean_query or query)
        if "no page" not in wiki_result and "multiple entries" not in wiki_result:
            raw_result = wiki_result
        else:
            raw_result = _duckduckgo_search(query)
    else:
        raw_result = _duckduckgo_search(query)

    # ── Optionally summarise with brain ────────────────────────────────────────
    if brain is not None:
        try:
            prompt = (
                f"The user asked: \"{query}\"\n\n"
                f"Here is the raw search result:\n{raw_result}\n\n"
                f"Please summarise this in 2–3 sentences in your JARVIS style."
            )
            return brain.ask_raw(prompt) or raw_result
        except Exception as exc:
            logger.error("Brain summarisation of search failed: %s", exc)

    return raw_result
