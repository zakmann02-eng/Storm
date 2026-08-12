"""Turns a parsed weather market + forecast(s) into a trade signal.

The probability estimate is a heuristic, not a calibrated model: for
rain/snow markets it uses precipitation-probability fields directly; for
temperature threshold markets it converts the forecast's distance from
the threshold into a probability via a logistic curve, which
approximates typical multi-day forecast error. Tune SIGNAL_TEMP_SCALE as
you gather evidence of how these markets actually resolve.

When both NWS and Open-Meteo forecasts are available, their estimates are
averaged - a small ensemble rather than relying on a single model's point
forecast, the same approach other Polymarket weather bots use (blending
GFS/ECMWF/ICON etc.). Either source alone still works fine on its own.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

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


def _temp_above_probability(forecast_extreme: float, threshold: float) -> float:
    diff = forecast_extreme - threshold
    return 1.0 / (1.0 + math.exp(-diff / SIGNAL_TEMP_SCALE))


def _estimate_from_nws(spec: WeatherMarketSpec, periods: list[dict]) -> float | None:
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
        prob_above = _temp_above_probability(forecast_extreme, spec.threshold)
        return prob_above if spec.variable == "temp_above" else 1.0 - prob_above

    return None


def _estimate_from_open_meteo(spec: WeatherMarketSpec, forecast: dict[str, Any] | None) -> float | None:
    if forecast is None:
        return None

    if spec.variable in ("rain", "snow"):
        pop = forecast.get("precipitation_probability_max")
        return pop / 100.0 if pop is not None else None

    if spec.variable in ("temp_above", "temp_below"):
        if spec.threshold is None:
            return None
        forecast_extreme = (
            forecast.get("temperature_max") if spec.variable == "temp_above" else forecast.get("temperature_min")
        )
        if forecast_extreme is None:
            return None
        prob_above = _temp_above_probability(forecast_extreme, spec.threshold)
        return prob_above if spec.variable == "temp_above" else 1.0 - prob_above

    return None


def estimate_yes_probability(
    spec: WeatherMarketSpec,
    periods: list[dict],
    open_meteo_forecast: dict[str, Any] | None = None,
) -> float | None:
    """Blends NWS and Open-Meteo estimates (simple average) when both are
    available; falls back to whichever one produced a usable estimate."""
    estimates = [
        e
        for e in (_estimate_from_nws(spec, periods), _estimate_from_open_meteo(spec, open_meteo_forecast))
        if e is not None
    ]
    if not estimates:
        return None
    return sum(estimates) / len(estimates)


def generate_signal(
    spec: WeatherMarketSpec,
    periods: list[dict],
    min_edge: float,
    open_meteo_forecast: dict[str, Any] | None = None,
) -> TradeSignal | None:
    estimated_yes = estimate_yes_probability(spec, periods, open_meteo_forecast)
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
