"""Turns a parsed weather market + NWS forecast into a trade signal.

The probability estimate is a heuristic, not a calibrated model: for
rain/snow markets it uses NWS's own probability-of-precipitation field
directly; for temperature threshold markets it converts the forecast's
distance from the threshold into a probability via a logistic curve, which
approximates typical multi-day NWS forecast error. Tune SIGNAL_TEMP_SCALE
as you gather evidence of how these markets actually resolve.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from storm.market_parser import WeatherMarketSpec
from storm.weather_client import period_date

# Degrees of forecast error treated as one logistic "step". Larger values
# make the estimate more conservative (closer to 50/50) for a given
# forecast/threshold gap.
SIGNAL_TEMP_SCALE = 3.0


@dataclass
class TradeSignal:
    market: WeatherMarketSpec
    side: str  # "YES" or "NO"
    estimated_probability: float
    market_probability: float
    edge: float


def estimate_yes_probability(spec: WeatherMarketSpec, periods: list[dict]) -> float | None:
    day_periods = [p for p in periods if period_date(p) == spec.target_date]
    if not day_periods:
        return None

    if spec.variable in ("rain", "snow"):
        pops = [
            p.get("probabilityOfPrecipitation", {}).get("value")
            for p in day_periods
            if p.get("probabilityOfPrecipitation")
        ]
        pops = [v for v in pops if v is not None]
        if not pops:
            return None
        return max(pops) / 100.0

    if spec.variable in ("temp_above", "temp_below"):
        daytime_temps = [p["temperature"] for p in day_periods if p.get("isDaytime") and "temperature" in p]
        temps = daytime_temps or [p["temperature"] for p in day_periods if "temperature" in p]
        if not temps or spec.threshold is None:
            return None
        forecast_extreme = max(temps) if spec.variable == "temp_above" else min(temps)
        diff = forecast_extreme - spec.threshold
        prob_above_threshold = 1.0 / (1.0 + math.exp(-diff / SIGNAL_TEMP_SCALE))
        return prob_above_threshold if spec.variable == "temp_above" else 1.0 - prob_above_threshold

    return None


def generate_signal(spec: WeatherMarketSpec, periods: list[dict], min_edge: float) -> TradeSignal | None:
    estimated_yes = estimate_yes_probability(spec, periods)
    if estimated_yes is None:
        return None

    market_yes = spec.yes_price
    edge_yes = estimated_yes - market_yes
    edge_no = (1.0 - estimated_yes) - (1.0 - market_yes)  # == -edge_yes, kept explicit for clarity

    if edge_yes >= min_edge:
        return TradeSignal(spec, "YES", estimated_yes, market_yes, edge_yes)
    if edge_no >= min_edge:
        return TradeSignal(spec, "NO", 1.0 - estimated_yes, 1.0 - market_yes, edge_no)
    return None
