"""The three airport locations Storm monitors and trades.

Deliberately narrow scope (vs. the ~20-city list Storm used to track) -
Storm is now focused specifically on these three, per explicit request.
Coordinates are the airports themselves (not city-center coordinates)
since forecast accuracy for a specific station matters for these markets.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Airport:
    code: str  # station code as used in real Polymarket.US market slugs
    name: str
    lat: float
    lon: float
    # Lowercase phrases that identify this airport in free-text market
    # questions/descriptions, for markets that don't use the tc-temp-*
    # slug convention (e.g. rain/snow markets).
    aliases: tuple[str, ...]


AIRPORTS: dict[str, Airport] = {
    "mia": Airport(
        code="mia",
        name="Miami International Airport",
        lat=25.7959,
        lon=-80.2870,
        aliases=("mia", "miami international", "miami"),
    ),
    "ord": Airport(
        code="ord",
        name="Chicago O'Hare International Airport",
        lat=41.9742,
        lon=-87.9073,
        # Note: real Polymarket.US market slugs observed so far use "mdw"
        # (Midway), not "ord" (O'Hare) - if O'Hare-specific markets never
        # show up, add an "mdw" entry here too (same city, different
        # station) rather than assuming Storm is broken.
        aliases=("ord", "o'hare", "ohare", "chicago o'hare", "chicago"),
    ),
    "lax": Airport(
        code="lax",
        name="Los Angeles International Airport",
        lat=33.9416,
        lon=-118.4085,
        aliases=("lax", "los angeles international", "los angeles"),
    ),
}


def find_airport_by_alias(lowered_text: str) -> Airport | None:
    """Longest alias first so e.g. "chicago o'hare" isn't shadowed by
    the shorter "chicago" alias of the same airport (harmless here, but
    keeps the pattern consistent if aliases overlap across airports)."""
    for airport in AIRPORTS.values():
        for alias in sorted(airport.aliases, key=len, reverse=True):
            if alias in lowered_text:
                return airport
    return None
