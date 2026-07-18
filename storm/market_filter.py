"""Keyword-based filtering to find weather markets among all Polymarket
markets, and to keep Storm out of Colossus's sports-league territory.

Polymarket doesn't reliably tag every market as "weather", so this filters
on question/slug/description/tag text. It's intentionally simple - false
negatives (missing an oddly-worded weather market) are safer than false
positives (Storm trading a market it doesn't understand).
"""

from __future__ import annotations

from typing import Any

WEATHER_KEYWORDS = (
    "temperature",
    "highest temp",
    "lowest temp",
    "high temp",
    "low temp",
    "rainfall",
    "rain in",
    "will it rain",
    "will it snow",
    "snowfall",
    "hurricane",
    "tropical storm",
    "tornado",
    "heat wave",
    "heatwave",
    "cold snap",
    "freeze",
    "frost",
    "wind speed",
    "humidity",
    "drought",
    "flood",
    "hottest day",
    "coldest day",
    "degrees f",
    "degrees c",
    "noaa",
    "national weather service",
    " nws ",
    "weather",
)

# Guard against phrases that contain "storm" or similar words but aren't
# meteorological (e.g. news/political commentary markets).
EXCLUDE_PHRASES = (
    "political storm",
    "brainstorm",
    "twitter storm",
    "social media storm",
    "shitstorm",
    "firestorm",
)


def _tag_text(tag: Any) -> str:
    if isinstance(tag, dict):
        return " ".join(str(v) for v in (tag.get("label"), tag.get("slug")) if v)
    return str(tag)


def _haystack(market: dict[str, Any]) -> str:
    text_fields = (
        str(market.get("question", "")),
        str(market.get("slug", "")),
        str(market.get("description", "")),
    )
    tags = market.get("tags") or []
    tag_text = " ".join(_tag_text(t) for t in tags)
    return f" {' '.join(text_fields)} {tag_text} ".lower()


def is_weather_market(market: dict[str, Any]) -> bool:
    haystack = _haystack(market)
    if any(bad in haystack for bad in EXCLUDE_PHRASES):
        return False
    return any(keyword in haystack for keyword in WEATHER_KEYWORDS)
