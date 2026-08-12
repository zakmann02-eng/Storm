"""Parses Polymarket.US's "tc-temp-*" range-bucket market slugs directly.

Confirmed real format from production data (Colossus's own trade log):
    tc-temp-{airport}{high|low}-{date}-gte{low}lt{high}f
e.g. "tc-temp-mdwhigh-2026-07-25-gte82lt83f" = Midway, daily high,
July 25 2026, bucket [82, 83) F.

This is more reliable than free-text parsing for these markets since the
slug itself encodes the exact bucket boundaries - nothing to guess at.
Markets that don't use this convention (e.g. rain/snow) still go through
market_parser.py's free-text parsing instead.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

_SLUG_RE = re.compile(
    r"^tc-temp-(?P<code>[a-z]+)(?P<extreme>high|low)-(?P<date>\d{4}-\d{2}-\d{2})-"
    r"gte(?P<low>-?\d+)lt(?P<high>-?\d+)f$"
)


@dataclass(frozen=True)
class TcTempBucket:
    airport_code: str
    extreme: str  # "high" or "low"
    target_date: dt.date
    low: float
    high: float


def parse_tc_temp_slug(slug: str) -> TcTempBucket | None:
    match = _SLUG_RE.match(slug)
    if not match:
        return None
    try:
        target_date = dt.date.fromisoformat(match.group("date"))
    except ValueError:
        return None
    return TcTempBucket(
        airport_code=match.group("code"),
        extreme=match.group("extreme"),
        target_date=target_date,
        low=float(match.group("low")),
        high=float(match.group("high")),
    )
