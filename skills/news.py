"""
skills/news.py — News headlines via NewsAPI (free tier).
Requires NEWS_API_KEY in .env.
"""

import logging
import requests
from config import NEWS_API_KEY

logger = logging.getLogger(__name__)

_NEWS_URL = "https://newsapi.org/v2/top-headlines"


def handle(query: str, brain=None) -> str:
    if not NEWS_API_KEY:
        return "The NewsAPI key is not configured, Sir. Please add NEWS_API_KEY to your .env file."

    try:
        lowered = query.lower()

        # Determine category / keyword
        category = None
        keyword = None
        cat_map = {
            "sports": "sports",
            "sport": "sports",
            "tech": "technology",
            "technology": "technology",
            "science": "science",
            "health": "health",
            "business": "business",
            "entertainment": "entertainment",
        }
        for word, cat in cat_map.items():
            if word in lowered:
                category = cat
                break

        params = {
            "apiKey": NEWS_API_KEY,
            "language": "en",
            "pageSize": 5,
        }
        if category:
            params["category"] = category
        else:
            params["country"] = "us"

        resp = requests.get(_NEWS_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        articles = data.get("articles", [])

        if not articles:
            return "I couldn't retrieve any headlines at this moment, Sir."

        lines = [f"Top {'headlines' if not category else category + ' news'}:"]
        for i, a in enumerate(articles[:5], 1):
            title = a.get("title", "No title")
            source = a.get("source", {}).get("name", "Unknown source")
            lines.append(f"  {i}. {title} — {source}")

        return "\n".join(lines)

    except requests.exceptions.HTTPError as exc:
        logger.error("NewsAPI HTTP error: %s", exc)
        return f"The news service returned an error: {exc}"
    except Exception as exc:
        logger.error("News error: %s", exc)
        return f"I was unable to fetch the news: {exc}"
