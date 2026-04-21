"""
skills/weather.py — OpenWeatherMap current weather + forecast skill.
Requires OPENWEATHER_API_KEY in .env (free tier).
"""

import logging
import re
import requests
from config import OPENWEATHER_API_KEY, CITY

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.openweathermap.org/data/2.5"


def _kelvin_to_celsius(k: float) -> float:
    return round(k - 273.15, 1)


def _get_current_weather(city: str) -> str:
    if not OPENWEATHER_API_KEY:
        return "The OpenWeatherMap API key is not configured, Sir. Please add it to your .env file."

    try:
        url = f"{_BASE_URL}/weather"
        params = {"q": city, "appid": OPENWEATHER_API_KEY}
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        desc = data["weather"][0]["description"].capitalize()
        temp_c = _kelvin_to_celsius(data["main"]["temp"])
        feels_c = _kelvin_to_celsius(data["main"]["feels_like"])
        humidity = data["main"]["humidity"]
        wind_kmh = round(data["wind"]["speed"] * 3.6, 1)
        city_name = data.get("name", city)
        country = data["sys"].get("country", "")

        return (
            f"Current weather in {city_name}, {country}: {desc}. "
            f"Temperature: {temp_c}°C (feels like {feels_c}°C). "
            f"Humidity: {humidity}%. Wind: {wind_kmh} km/h."
        )

    except requests.exceptions.HTTPError as exc:
        if exc.response.status_code == 404:
            return f"I couldn't find weather data for '{city}', Sir. Please verify the city name."
        return f"Weather API returned an error: {exc}"
    except Exception as exc:
        logger.error("Weather error: %s", exc)
        return f"I was unable to retrieve the weather: {exc}"


def _get_forecast(city: str) -> str:
    """Get a 3-day simplified forecast."""
    if not OPENWEATHER_API_KEY:
        return "OpenWeatherMap API key not configured, Sir."

    try:
        url = f"{_BASE_URL}/forecast"
        params = {"q": city, "appid": OPENWEATHER_API_KEY, "cnt": 8}  # 8 × 3h = 24h
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        lines = [f"Forecast for {city}:"]
        seen_dates: set = set()

        for item in data.get("list", []):
            dt_txt = item["dt_txt"]
            day = dt_txt.split(" ")[0]
            if day in seen_dates:
                continue
            seen_dates.add(day)
            desc = item["weather"][0]["description"].capitalize()
            temp_c = _kelvin_to_celsius(item["main"]["temp"])
            lines.append(f"  {day}: {desc}, {temp_c}°C")
            if len(seen_dates) >= 3:
                break

        return "\n".join(lines)

    except Exception as exc:
        logger.error("Forecast error: %s", exc)
        return f"Unable to retrieve forecast: {exc}"


# ── City extraction ──────────────────────────────────────────────────────────
# Words that appear after 'in / for / at' in weather queries but are NOT cities.
_NON_CITY_WORDS: set[str] = {
    "is", "the", "a", "an", "be", "me", "my", "weather", "forecast",
    "today", "tomorrow", "now", "currently", "outside", "like", "going",
    "what", "whats", "give", "get", "show", "tell", "check", "how",
    "please", "jarvis", "hey", "sir", "about", "of", "that", "this",
    "days", "next", "few", "current", "update", "right", "there",
}

_CITY_RE = re.compile(
    r'\b(?:in|for|from|at|of)\s+'
    r'([A-Za-z][A-Za-z\s]{1,30}?)'
    r'(?=\s*[?]|\s*$|\s+(?:today|tomorrow|now|please|forecast|weather|right|temperature))',
    re.IGNORECASE,
)

# Adjacency fallback: catches 'Delhi weather', 'weather Delhi'.
# Only matches TITLE-CASE words (city names) so filler words like 'What', 'is',
# 'the' are excluded (they are lowercase or filtered by _NON_CITY_WORDS).
_CITY_ADJACENT_RE = re.compile(
    r'(?:'
    r'([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)'
    r'\s+(?:weather|forecast|temperature|temp|rain|humid|wind)'
    r'|'
    r'(?:weather|forecast|temperature|temp|rain|humid|wind)'
    r'\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)'
    r')(?:\s|$|[?])',
)

# Whisper commonly mishears 'from' as 'form' — normalise before extraction.
_MISHEAR_MAP = {
    "form ": "from ",
    "weather form ": "weather from ",
}


def _extract_city(query: str) -> str:
    """
    Extract a city name from the query. Strategy (in order of confidence):

    1. Normalise Whisper misheard words ('form' → 'from' etc.)
    2. Preposition anchor: 'weather in Delhi', 'forecast from New York'
    3. Adjacency fallback: 'Delhi weather', 'weather Delhi'
    4. Config default: falls back to the CITY value from config.py.
    """
    # Step 0 — normalise common Whisper misheard words
    normalised = query
    for mishear, correct in _MISHEAR_MAP.items():
        normalised = re.sub(re.escape(mishear), correct, normalised, flags=re.IGNORECASE)

    # Pass 1 — preposition-anchored (highest confidence)
    match = _CITY_RE.search(normalised)
    if match:
        candidate = match.group(1).strip().rstrip("?.,!")
        if candidate.lower() not in _NON_CITY_WORDS:
            return candidate

    # Pass 2 — adjacency pattern (handles "Delhi weather" / "weather Mumbai")
    match = _CITY_ADJACENT_RE.search(normalised)
    if match:
        candidate = (match.group(1) or match.group(2) or "").strip().rstrip("?.,!")
        if candidate and candidate.lower() not in _NON_CITY_WORDS:
            return candidate

    return CITY



def handle(query: str, brain=None) -> str:
    """
    Main entry point for WEATHER intent.
    Detects 'forecast' queries vs. current weather.
    """
    lowered = query.lower()

    # FIX Bug 1+3: use regex extractor instead of brittle keyword index scan
    city = _extract_city(query)

    if "forecast" in lowered or "tomorrow" in lowered or "next few days" in lowered:
        return _get_forecast(city)
    return _get_current_weather(city)
