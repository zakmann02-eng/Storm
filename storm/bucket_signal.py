"""Probability math for range-bucket weather markets.

Some Polymarket.US weather questions ("Highest temperature in NYC on
July 18?") aren't a single Yes/No threshold - they're one event grouping
several mutually exclusive range-bucket outcomes ("78 or below", "79 to
80", "81 to 82", ..., "87 or above"), each independently priced. Storm's
main signal_engine.py assumes a single threshold and doesn't handle this
shape.

This module is the standalone probability math for that case: model the
day's forecast temperature as a normal distribution (mean = forecast
value, stdev = assumed forecast error) and integrate it over each
bucket's [low, high) range to get Storm's own estimated probability for
that specific bucket, then compare to that bucket's actual market price -
the same approach other Polymarket weather bots use (build a
distribution, price each bucket, trade whichever is mispriced).

Wired into storm/bot.py via storm/tc_temp_parser.py, which parses the
bucket boundaries directly out of Polymarket.US's real "tc-temp-*" market
slug format (confirmed from production data) - each such market is
evaluated as a single bucket via evaluate_bucket(); generate_bucket_signals
below evaluates several buckets from one grouped event at once, for
whenever that grouped-event shape is also confirmed and wired in.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist


@dataclass
class TemperatureBucket:
    market_slug: str
    condition_id: str
    low: float | None  # None = unbounded below, e.g. "78 or below" -> low=None, high=78
    high: float | None  # None = unbounded above, e.g. "87 or above" -> low=87, high=None
    yes_price: float


@dataclass
class BucketSignal:
    bucket: TemperatureBucket
    side: str  # "YES" or "NO"
    estimated_probability: float
    market_probability: float
    edge: float


def bucket_probability(mean: float, stdev: float, low: float | None, high: float | None) -> float:
    """P(low <= temperature < high) under a normal model of the day's
    temperature, given the forecast mean and an assumed forecast-error
    stdev. Either bound may be None for an open-ended bucket."""
    if stdev <= 0:
        raise ValueError("stdev must be positive")
    if low is not None and high is not None and low >= high:
        raise ValueError("low must be less than high")

    dist = NormalDist(mean, stdev)
    upper = dist.cdf(high) if high is not None else 1.0
    lower = dist.cdf(low) if low is not None else 0.0
    return max(0.0, min(1.0, upper - lower))


def evaluate_bucket(
    bucket: TemperatureBucket,
    forecast_mean: float,
    forecast_stdev: float,
    min_edge: float,
) -> BucketSignal | None:
    """Evaluate a single bucket against a forecast distribution. Returns
    None if the edge (either side) doesn't clear min_edge."""
    estimated_yes = bucket_probability(forecast_mean, forecast_stdev, bucket.low, bucket.high)
    market_yes = bucket.yes_price
    edge_yes = estimated_yes - market_yes
    edge_no = (1.0 - estimated_yes) - (1.0 - market_yes)

    if edge_yes >= min_edge:
        return BucketSignal(bucket, "YES", estimated_yes, market_yes, edge_yes)
    if edge_no >= min_edge:
        return BucketSignal(bucket, "NO", 1.0 - estimated_yes, 1.0 - market_yes, edge_no)
    return None


def generate_bucket_signals(
    buckets: list[TemperatureBucket],
    forecast_mean: float,
    forecast_stdev: float,
    min_edge: float,
) -> list[BucketSignal]:
    """Evaluate every bucket in an event against the same forecast
    distribution, returning a signal for each bucket whose edge clears
    min_edge (there may be more than one, though typically at most the
    bucket(s) nearest the forecast mean will show a real edge)."""
    signals = [evaluate_bucket(b, forecast_mean, forecast_stdev, min_edge) for b in buckets]
    return [s for s in signals if s is not None]
