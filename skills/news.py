"""
skills/news.py — News headlines via NewsAPI (free tier).
Requires NEWS_API_KEY in .env.

Supported voice commands:
  "latest news" / "headlines"                → US top headlines (country=us)
  "tech news" / "technology news"           → technology category
  "sports news"                              → sports category
  "science / health / business / entertainment news" → respective category
  "india news" / "Indian news"              → queries 'india' as a keyword
                                               (free tier doesn't support in-country)
"""

import logging
import requests
from config import NEWS_API_KEY

logger = logging.getLogger(__name__)

_NEWS_URL = "https://newsapi.org/v2/top-headlines"
_EVERYTHING_URL = "https://newsapi.org/v2/everything"


def handle(query: str, brain=None) -> str:
    if not NEWS_API_KEY:
        return (
            "The NewsAPI key is not configured, Sir. "
            "Please add NEWS_API_KEY to your .env file."
        )

    try:
        lowered = query.lower()

        # ── Category detection ──────────────────────────────────────────────
        category = None
        cat_map = {
            "sports":        "sports",
            "sport":         "sports",
            "tech":          "technology",
            "technology":    "technology",
            "science":       "science",
            "health":        "health",
            "business":      "business",
            "entertainment": "entertainment",
        }
        for word, cat in cat_map.items():
            if word in lowered:
                category = cat
                break

        # ── India keyword detection ─────────────────────────────────────────
        # Free tier country=in returns 0 articles; use keyword search instead
        india_keywords = ["india", "indian", "bharat", "desh"]
        wants_india = any(kw in lowered for kw in india_keywords)

        # ── Build params ────────────────────────────────────────────────────
        if wants_india:
            # Use /everything with 'India' as keyword — free tier supports this
            params = {
                "apiKey":   NEWS_API_KEY,
                "q":        "India",
                "language": "en",
                "pageSize": 5,
                "sortBy":   "publishedAt",
            }
            url   = _EVERYTHING_URL
            label = "India"
        elif category:
            params = {
                "apiKey":    NEWS_API_KEY,
                "category":  category,
                "language":  "en",
                "pageSize":  5,
                "country":   "us",
            }
            url   = _NEWS_URL
            label = category
        else:
            params = {
                "apiKey":   NEWS_API_KEY,
                "country":  "us",
                "language": "en",
                "pageSize": 5,
            }
            url   = _NEWS_URL
            label = "top"

        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data     = resp.json()
        articles = data.get("articles", [])

        if not articles:
            return "I couldn't retrieve any headlines at this moment, Sir."

        headline_word = "headlines" if label == "top" else f"{label} news"
        lines = [f"Here are the {headline_word}, Sir:"]
        for i, a in enumerate(articles[:5], 1):
            title  = a.get("title") or "No title"
            # Strip the " - Source Name" suffix NewsAPI appends to titles
            if " - " in title:
                title = title.rsplit(" - ", 1)[0].strip()
            source = a.get("source", {}).get("name", "Unknown")
            lines.append(f"{i}. {title} — {source}")

        return "\n".join(lines)

    except requests.exceptions.HTTPError as exc:
        logger.error("NewsAPI HTTP error: %s", exc)
        return f"The news service returned an error, Sir: {exc}"
    except requests.exceptions.ConnectionError:
        return "I was unable to connect to the news service. Please check your internet connection, Sir."
    except Exception as exc:
        logger.error("News error: %s", exc)
        return f"I was unable to fetch the news: {exc}"
