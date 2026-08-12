"""Parses a Gamma market's question/description into a structured
WeatherMarketSpec that the signal engine can reason about.

This is heuristic by nature - Polymarket doesn't provide structured
weather-market metadata, only free text. Markets Storm can't confidently
parse are skipped (returns None) rather than guessed at. Location
matching is restricted to storm/airports.py's three tracked airports
(MIA, ORD, LAX) - Storm no longer monitors the broader city list it used
to. Extend the keyword lists below as new phrasing shows up in markets
Storm is missing for those three.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

from storm.airports import find_airport_by_alias

_ABOVE_WORDS = ("above", "over", "exceed", "exceeds", "higher than", "greater than", "more than", "hotter than")
_BELOW_WORDS = ("below", "under", "less than", "lower than", "colder than")
_TEMP_CONTEXT_WORDS = ("temperature", "temp ", "temp.", "degree", "°f", "°c", "high of", "low of")

_THRESHOLD_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:°|degrees?)?\s*f\b|(-?\d+(?:\.\d+)?)\s*(?:°|degrees?)\b")


@dataclass
class WeatherMarketSpec:
    condition_id: str
    market_slug: str
    question: str
    location: str
    lat: float
    lon: float
    variable: str  # "temp_above", "temp_below", "rain", "snow"
    threshold: float | None
    target_date: dt.date
    yes_price: float


def _find_location(lowered_text: str) -> tuple[str, float, float] | None:
    airport = find_airport_by_alias(lowered_text)
    if airport is None:
        return None
    return airport.code, airport.lat, airport.lon


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
    market_slug: str,
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
        condition_id=str(market.get("id") or market.get("conditionId") or ""),
        market_slug=market_slug,
        question=question,
        location=location,
        lat=lat,
        lon=lon,
        variable=variable,
        threshold=threshold,
        target_date=target_date,
        yes_price=yes_price,
    )
