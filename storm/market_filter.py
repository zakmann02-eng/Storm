"""Keyword-based filtering to find weather markets among all Polymarket
markets, and to keep Storm out of Colossus's sports-league territory.

Polymarket.US groups all weather markets (temperature, rain, snow,
storms) under a single "Temp" category/tag in the app - CATEGORY_TAGS
below is an exact-match check against that (plus a couple of likely
variants), which is far more reliable than free-text keyword matching.
It's checked first; the keyword heuristic on question/slug/description
text remains as a fallback for markets that lack clean category/tag data.
False negatives (missing an oddly-worded weather market) are safer than
false positives (Storm trading a market it doesn't understand).
"""

from __future__ import annotations

from typing import Any

# Exact (not substring) match against a market's category field or a tag's
# label/slug. Deliberately exact rather than substring - "temp" as a
# substring would false-positive on unrelated words (temporary, attempt,
# template, ...).
CATEGORY_TAGS = {"temp", "temps", "weather"}

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


def _tag_labels(market: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    category = market.get("category")
    if category:
        labels.add(str(category).strip().lower())
    for tag in market.get("tags") or []:
        if isinstance(tag, dict):
            for key in ("label", "slug"):
                val = tag.get(key)
                if val:
                    labels.add(str(val).strip().lower())
        elif tag:
            labels.add(str(tag).strip().lower())
    return labels


def _is_structurally_sports(market: dict[str, Any]) -> bool:
    """Confirmed from Polymarket.US's own OpenAPI schema: "sportsMarketType"
    (e.g. SPORTS_MARKET_TYPE_MONEYLINE) is populated only on sports
    markets, and tags carry "sport"/"league" sub-objects only for sports
    tags. These are structured signals, not text guesses - more precise
    than the category-string check for catching sports markets that
    happen to have thin/missing category data."""
    if market.get("sportsMarketType"):
        return True
    for tag in market.get("tags") or []:
        if isinstance(tag, dict) and (tag.get("sport") or tag.get("league")):
            return True
    return False


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
    # Primary signal: Polymarket.US files all weather markets under a
    # single "Temp" category/tag - an exact match here is far more
    # reliable than free-text keyword guessing.
    if _tag_labels(market) & CATEGORY_TAGS:
        return True

    if _is_structurally_sports(market):
        return False

    # If the market has an explicit, non-weather category, trust it and
    # stop there - don't fall through to keyword matching. Sports team
    # names collide with weather vocabulary often enough to matter (e.g.
    # an NHL "Panthers vs Hurricanes" market matching "hurricane"), and a
    # market Gamma/the SDK already categorized isn't one we should be
    # second-guessing with free text.
    category = str(market.get("category") or "").strip().lower()
    if category and category not in CATEGORY_TAGS:
        return False

    # Fallback for markets with missing/inconsistent category data.
    haystack = _haystack(market)
    if any(bad in haystack for bad in EXCLUDE_PHRASES):
        return False
    return any(keyword in haystack for keyword in WEATHER_KEYWORDS)
