"""
skills/web_search.py — DuckDuckGo + Wikipedia search skill for J.A.R.V.I.S.
No API key required — completely free.
"""

import logging
from typing import Optional
import urllib.parse
import base64
from curl_cffi import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def _clean_bing_url(url: str) -> str:
    """Extract and decode clean URL from Bing redirection wrapper."""
    if "/ck/a?!" in url or "bing.com/ck/a?!" in url:
        try:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            if "u" in qs:
                u_val = qs["u"][0]
                if len(u_val) > 2:
                    encoded_part = u_val[2:]
                    padding = len(encoded_part) % 4
                    if padding:
                        encoded_part += "=" * (4 - padding)
                    decoded = base64.b64decode(encoded_part).decode("utf-8", errors="ignore")
                    if decoded.startswith("http"):
                        return decoded
        except Exception:
            pass
    return url


def _duckduckgo_search(query: str, max_results: int = 3) -> str:
    """Search DuckDuckGo HTML and fallback to Bing Search using curl_cffi browser impersonation."""
    results = []

    # ── Stage 1: DuckDuckGo HTML Search ───────────────────────────
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        resp = requests.get(url, impersonate="chrome120", timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for r in soup.find_all("div", class_="result"):
                title_a = r.find("a", class_="result__a")
                snippet_a = r.find("a", class_="result__snippet")
                if title_a:
                    title = title_a.text.strip()
                    href = title_a.get("href", "")
                    
                    # Clean DDG redirect URL
                    if "uddg=" in href:
                        parsed = urllib.parse.urlparse(href)
                        qs = urllib.parse.parse_qs(parsed.query)
                        if "uddg" in qs:
                            href = qs["uddg"][0]
                    
                    snippet = snippet_a.text.strip() if snippet_a else ""
                    if not title or "duckduckgo.com/y.js" in href:
                        continue
                    results.append({
                        "title": title,
                        "href": href,
                        "body": snippet[:200]
                    })
    except Exception as exc:
        logger.warning("DuckDuckGo HTML search failed: %s", exc)

    # ── Stage 2: Fallback to Bing Search if DDG yielded no results ────────────────
    if not results:
        try:
            logger.info("DuckDuckGo returned no results; falling back to Bing Search...")
            url = f"https://www.bing.com/search?q={urllib.parse.quote(query)}"
            resp = requests.get(url, impersonate="chrome120", timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for li in soup.find_all("li", class_="b_algo"):
                    h2 = li.find("h2")
                    if not h2:
                        continue
                    a = h2.find("a")
                    if not a:
                        continue
                    title = a.text.strip()
                    href = _clean_bing_url(a.get("href", ""))
                    
                    caption_div = li.find("div", class_="b_caption")
                    snippet = ""
                    if caption_div:
                        p = caption_div.find("p")
                        if p:
                            snippet = p.text.strip()
                    if not snippet:
                        p_tag = li.find("p")
                        if p_tag:
                            snippet = p_tag.text.strip()
                            
                    if not title or not href:
                        continue
                    results.append({
                        "title": title,
                        "href": href,
                        "body": snippet[:200]
                    })
        except Exception as exc:
            logger.warning("Bing search fallback failed: %s", exc)

    # ── Formatting Results ──────────────────────────────────────────
    if not results:
        return "I found no results for that query on the web, Sir."

    lines = [f"Here are the top results for '{query}':"]
    for i, r in enumerate(results[:max_results], 1):
        title = r.get("title", "Unknown")
        body = r.get("body", "")
        url = r.get("href", "")
        lines.append(f"\n{i}. {title}\n   {body}\n   Source: {url}")

    return "\n".join(lines)


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
