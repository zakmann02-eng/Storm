"""Parses a Gamma market's question/description into a structured
WeatherMarketSpec that the signal engine can reason about.

This is heuristic by nature - Polymarket doesn't provide structured
weather-market metadata, only free text. Markets Storm can't confidently
parse are skipped (returns None) rather than guessed at. Extend
CITY_COORDINATES and the keyword lists below as new phrasing/cities show
up in markets Storm is missing.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

# Major US cities Polymarket weather markets commonly reference, mapped to
# lat/lon for NWS point lookups.
CITY_COORDINATES: dict[str, tuple[float, float]] = {
    "new york city": (40.7128, -74.0060),
    "new york": (40.7128, -74.0060),
    "nyc": (40.7128, -74.0060),
    "los angeles": (34.0522, -118.2437),
    "chicago": (41.8781, -87.6298),
    "houston": (29.7604, -95.3698),
    "phoenix": (33.4484, -112.0740),
    "philadelphia": (39.9526, -75.1652),
    "san antonio": (29.4241, -98.4936),
    "san diego": (32.7157, -117.1611),
    "dallas": (32.7767, -96.7970),
    "austin": (30.2672, -97.7431),
    "miami": (25.7617, -80.1918),
    "atlanta": (33.7490, -84.3880),
    "boston": (42.3601, -71.0589),
    "seattle": (47.6062, -122.3321),
    "denver": (39.7392, -104.9903),
    "washington dc": (38.9072, -77.0369),
    "washington d.c.": (38.9072, -77.0369),
    "las vegas": (36.1699, -115.1398),
    "san francisco": (37.7749, -122.4194),
    "minneapolis": (44.9778, -93.2650),
    "detroit": (42.3314, -83.0458),
}

_ABOVE_WORDS = ("above", "over", "exceed", "exceeds", "higher than", "greater than", "more than", "hotter than")
_BELOW_WORDS = ("below", "under", "less than", "lower than", "colder than")
_TEMP_CONTEXT_WORDS = ("temperature", "temp ", "temp.", "degree", "°f", "°c", "high of", "low of")

_THRESHOLD_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:°|degrees?)?\s*f\b|(-?\d+(?:\.\d+)?)\s*(?:°|degrees?)\b")


@dataclass
class WeatherMarketSpec:
    condition_id: str
    yes_token_id: str
    no_token_id: str
    question: str
    location: str
    lat: float
    lon: float
    variable: str  # "temp_above", "temp_below", "rain", "snow"
    threshold: float | None
    target_date: dt.date
    yes_price: float


def _find_location(lowered_text: str) -> tuple[str, float, float] | None:
    # Longest name first so "new york city" isn't shadowed by "new york".
    for city in sorted(CITY_COORDINATES, key=len, reverse=True):
        if city in lowered_text:
            lat, lon = CITY_COORDINATES[city]
            return city, lat, lon
    return None


def _has_temp_context(lowered_text: str) -> bool:
    return any(w in lowered_text for w in _TEMP_CONTEXT_WORDS)


def _detect_variable(lowered_text: str) -> str | None:
    if "snow" in lowered_text:
        return "snow"
    if "rain" in lowered_text or "precipitation" in lowered_text:
        return "rain"
    if _has_temp_context(lowered_text):
        if any(w in lowered_text for w in _ABOVE_WORDS):
            return "temp_above"
        if any(w in lowered_text for w in _BELOW_WORDS):
            return "temp_below"
    return None


def _extract_threshold(text: str) -> float | None:
    match = _THRESHOLD_RE.search(text)
    if not match:
        return None
    value = match.group(1) or match.group(2)
    return float(value)


def _resolve_target_date(market: dict[str, Any]) -> dt.date | None:
    """Storm uses the market's endDate as the target date rather than
    parsing a date out of the question text - Polymarket's daily weather
    markets consistently resolve on the day the measured event occurs, so
    this is more reliable than free-text date parsing."""
    end_date = market.get("endDate")
    if not end_date:
        return None
    try:
        return dt.datetime.fromisoformat(str(end_date).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_weather_market(
    market: dict[str, Any],
    yes_token_id: str,
    no_token_id: str,
    yes_price: float,
) -> WeatherMarketSpec | None:
    question = market.get("question") or ""
    description = market.get("description") or ""
    text = f"{question} {description}"
    lowered = text.lower()

    location_match = _find_location(lowered)
    if location_match is None:
        return None
    location, lat, lon = location_match

    variable = _detect_variable(lowered)
    if variable is None:
        return None

    threshold = None
    if variable in ("temp_above", "temp_below"):
        threshold = _extract_threshold(text)
        if threshold is None:
            return None

    target_date = _resolve_target_date(market)
    if target_date is None:
        return None

    return WeatherMarketSpec(
        condition_id=market.get("conditionId", ""),
        yes_token_id=yes_token_id,
        no_token_id=no_token_id,
        question=question,
        location=location,
        lat=lat,
        lon=lon,
        variable=variable,
        threshold=threshold,
        target_date=target_date,
        yes_price=yes_price,
    )
