"""Extracts a [yes_price, no_price] pair from a market dict, regardless of
which pricing representation the source uses.

Confirmed from Polymarket.US's own OpenAPI schema (GET /v1/markets):
"outcomePrices" (Gamma's stringified-JSON-list format) is marked
deprecated there - the modern representation is "marketSides", an array
of long/short sides each carrying their own price. Gamma API fallback
data (storm/gamma_client.py) still uses the legacy outcomePrices format,
so this tries marketSides first and falls back to it.
"""

from __future__ import annotations

from typing import Any

from storm.gamma_client import parse_outcome_prices


def _side_price(side: dict[str, Any]) -> float | None:
    raw = side.get("price")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    quote = side.get("quote") or {}
    raw_quote = quote.get("value")
    if raw_quote is not None:
        try:
            return float(raw_quote)
        except (TypeError, ValueError):
            pass
    return None


def _prices_from_market_sides(sides: list[dict[str, Any]]) -> list[float] | None:
    long_price: float | None = None
    short_price: float | None = None
    for side in sides:
        price = _side_price(side)
        if price is None:
            continue
        if side.get("long") is True:
            long_price = price
        elif side.get("long") is False:
            short_price = price

    if long_price is None:
        return None
    if short_price is None:
        short_price = 1.0 - long_price
    return [long_price, short_price]


def parse_yes_no_prices(market: dict[str, Any]) -> list[float]:
    """Returns [yes_price, no_price], preferring the modern "marketSides"
    representation and falling back to the legacy "outcomePrices" one."""
    sides = market.get("marketSides")
    if sides:
        prices = _prices_from_market_sides(sides)
        if prices is not None:
            return prices

    return parse_outcome_prices(market)
