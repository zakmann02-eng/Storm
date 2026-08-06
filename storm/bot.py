"""Orchestrates one scan-and-trade cycle: discover markets, filter to
weather, parse, pull a forecast, and hand any signal to the trader.

Two parsing paths for a weather-tagged market:
1. "tc-temp-*" slugs (storm/tc_temp_parser.py) - Polymarket.US's real
   range-bucket temperature market format, confirmed from production
   data. Priced via storm/bucket_signal.py's normal-distribution model.
2. Everything else (rain/snow, or threshold-phrased markets) - the
   original free-text parser (storm/market_parser.py + signal_engine.py).

Every market processed (whether or not it produces a signal) is recorded
into the optional DashboardState for the real-time dashboard.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from collections import Counter
from typing import Any

from storm.airports import AIRPORTS, Airport
from storm.bucket_signal import BucketSignal, TemperatureBucket, evaluate_bucket
from storm.dashboard_state import DashboardState
from storm.gamma_client import GammaClient
from storm.market_filter import is_weather_market
from storm.market_parser import WeatherMarketSpec, parse_weather_market
from storm.market_pricing import parse_yes_no_prices
from storm.openmeteo_client import OpenMeteoClient
from storm.risk_manager import RiskManager
from storm.signal_engine import TradeSignal, generate_signal
from storm.tc_temp_parser import parse_tc_temp_slug
from storm.trader import Trader
from storm.us_client import USClient
from storm.weather_client import NWSClient, period_date

logger = logging.getLogger(__name__)

# How many unparseable-but-weather-tagged markets to dump full raw JSON for,
# per process lifetime. Temporary-ish diagnostic aid for tuning
# market_parser.py against real market shapes; capped so it can't spam logs.
_MAX_DIAGNOSTIC_DUMPS = 10

# Loose, filter-independent terms used only for the one-time discovery
# diagnostic below - deliberately broader than market_filter.py's real
# keyword list, to surface candidates even if is_weather_market() itself
# is wrong about what counts as a match.
_LOOSE_DIAGNOSTIC_TERMS = ("temp", "rain", "snow", "weather", "degree", "hurricane", "storm")
_MAX_LOOSE_DIAGNOSTIC_DUMPS = 5

# Candidate category strings to explicitly probe for, to tell "this
# account/key can't see Temp markets at all" apart from "the unfiltered
# default query just doesn't surface them".
_CATEGORY_PROBE_CANDIDATES = ("Temp", "temp", "weather", "Weather", "Temps")

# Assumed forecast-error stdev (degrees F) for the bucket probability
# model - same scale signal_engine.py uses for its logistic curve.
_BUCKET_FORECAST_STDEV = 3.0


def _nws_forecast_extreme(periods: list[dict], target_date: dt.date, extreme: str) -> float | None:
    day_periods = [p for p in periods if period_date(p) == target_date]
    if extreme == "high":
        temps = [p["temperature"] for p in day_periods if p.get("isDaytime") and "temperature" in p]
    else:
        temps = [p["temperature"] for p in day_periods if not p.get("isDaytime") and "temperature" in p]
    temps = temps or [p["temperature"] for p in day_periods if "temperature" in p]
    if not temps:
        return None
    return max(temps) if extreme == "high" else min(temps)


class StormBot:
    def __init__(
        self,
        us_client: USClient,
        gamma_client: GammaClient,
        weather_client: NWSClient,
        trader: Trader,
        risk_manager: RiskManager,
        min_edge: float,
        open_meteo_client: OpenMeteoClient | None = None,
        diagnostic_probe_slug: str = "",
        dashboard_state: DashboardState | None = None,
    ):
        self._us_client = us_client
        self._gamma_client = gamma_client
        self._weather_client = weather_client
        self._open_meteo_client = open_meteo_client
        self._trader = trader
        self._risk_manager = risk_manager
        self._min_edge = min_edge
        self._diagnostic_probe_slug = diagnostic_probe_slug
        self._dashboard_state = dashboard_state
        self._diagnostic_dumps = 0
        self._logged_discovery_diagnostics = False
        self._forecast_cache: dict[tuple[str, dt.date, str], float | None] = {}

    def run_cycle(self) -> None:
        if os.getenv("PAUSED", "false").lower() == "true":
            logger.info("Bot paused - skipping scan")
            return

        self._forecast_cache = {}

        markets = self._discover_markets()
        self._log_discovery_diagnostics(markets)
        weather_markets = [m for m in markets if is_weather_market(m)]
        logger.info("Scanned %d active markets, %d look weather-related", len(markets), len(weather_markets))
        if self._dashboard_state is not None:
            self._dashboard_state.record_scan_summary(len(markets), len(weather_markets))

        for market in weather_markets:
            if os.getenv("PAUSED", "false").lower() == "true":
                logger.info("Bot paused mid-scan - stopping")
                return
            try:
                self._process_market(market)
            except Exception:
                logger.exception("Error processing market %s", market.get("slug") or market.get("question"))

    def _discover_markets(self) -> list[dict[str, Any]]:
        try:
            markets = self._us_client.list_markets()
            if markets:
                return markets
            logger.warning("polymarket-us events.list() returned no markets - falling back to Gamma API")
        except Exception:
            logger.exception("polymarket-us events.list() failed - falling back to Gamma API")
        return list(self._gamma_client.iter_active_markets())

    def _process_market(self, market: dict[str, Any]) -> None:
        # Polymarket.US's own Market schema uses "id" as the unique
        # identifier; "conditionId" is the legacy polymarket.com/Gamma
        # naming, kept as a fallback for the Gamma fallback path.
        condition_id = str(market.get("id") or market.get("conditionId") or "")
        if condition_id and self._risk_manager.already_traded(condition_id):
            logger.debug("Already traded %s today - skipping", condition_id)
            return

        market_slug = market.get("slug") or ""
        prices = parse_yes_no_prices(market)
        if not market_slug or len(prices) != 2:
            logger.debug("Skipping %s: missing slug/prices", market.get("slug"))
            return
        yes_price = prices[0]

        tc_bucket = parse_tc_temp_slug(market_slug)
        if tc_bucket is not None:
            self._process_tc_temp_market(market_slug, condition_id, yes_price, tc_bucket)
            return

        spec = parse_weather_market(market, market_slug, yes_price)
        if spec is None:
            self._log_diagnostic_sample(market)
            return
        self._process_threshold_market(spec)

    # --- tc-temp-* range-bucket markets ---

    def _process_tc_temp_market(self, market_slug: str, condition_id: str, yes_price: float, tc_bucket) -> None:
        airport = AIRPORTS.get(tc_bucket.airport_code)
        if airport is None:
            return  # not one of the three tracked airports

        forecast_mean = self._forecast_mean(airport, tc_bucket.target_date, tc_bucket.extreme)
        if forecast_mean is None:
            logger.debug("No forecast available yet for %s on %s", airport.code, tc_bucket.target_date)
            return

        bucket = TemperatureBucket(
            market_slug=market_slug,
            condition_id=condition_id,
            low=tc_bucket.low,
            high=tc_bucket.high,
            yes_price=yes_price,
        )
        signal = evaluate_bucket(bucket, forecast_mean, _BUCKET_FORECAST_STDEV, self._min_edge)

        self._record_market_dashboard(
            airport, market_slug,
            {
                "type": "tc-temp",
                "extreme": tc_bucket.extreme,
                "target_date": tc_bucket.target_date.isoformat(),
                "bucket_low": bucket.low,
                "bucket_high": bucket.high,
                "market_yes_price": yes_price,
                "forecast_mean": forecast_mean,
                "estimated_probability": signal.estimated_probability if signal else None,
                "edge": signal.edge if signal else None,
                "side": signal.side if signal else None,
            },
        )

        if signal is None:
            return

        trade_signal = self._bucket_signal_to_trade_signal(signal, airport, tc_bucket, market_slug, condition_id)
        self._record_history(airport, trade_signal, market_type="tc-temp")
        self._trader.execute(trade_signal)

    def _bucket_signal_to_trade_signal(
        self, signal: BucketSignal, airport: Airport, tc_bucket, market_slug: str, condition_id: str
    ) -> TradeSignal:
        low_label = "unbounded" if tc_bucket.low is None else f"{tc_bucket.low:g}"
        high_label = "unbounded" if tc_bucket.high is None else f"{tc_bucket.high:g}"
        spec = WeatherMarketSpec(
            condition_id=condition_id,
            market_slug=market_slug,
            question=f"{airport.name} daily {tc_bucket.extreme} {low_label}-{high_label}F on {tc_bucket.target_date}",
            location=airport.code,
            lat=airport.lat,
            lon=airport.lon,
            variable=f"temp_{tc_bucket.extreme}_bucket",
            threshold=tc_bucket.low if tc_bucket.low is not None else tc_bucket.high,
            target_date=tc_bucket.target_date,
            yes_price=signal.bucket.yes_price,
        )
        return TradeSignal(
            market=spec,
            side=signal.side,
            estimated_probability=signal.estimated_probability,
            market_probability=signal.market_probability,
            edge=signal.edge,
        )

    def _forecast_mean(self, airport: Airport, target_date: dt.date, extreme: str) -> float | None:
        cache_key = (airport.code, target_date, extreme)
        if cache_key in self._forecast_cache:
            return self._forecast_cache[cache_key]

        nws_periods = self._weather_client.get_forecast_for_date(airport.lat, airport.lon, target_date)
        nws_value = _nws_forecast_extreme(nws_periods, target_date, extreme) if nws_periods else None

        om_value = None
        om_forecast = self._fetch_open_meteo(airport, target_date)
        if om_forecast is not None:
            om_value = om_forecast.get("temperature_max") if extreme == "high" else om_forecast.get("temperature_min")

        values = [v for v in (nws_value, om_value) if v is not None]
        mean = sum(values) / len(values) if values else None
        self._forecast_cache[cache_key] = mean

        if mean is not None:
            self._record_weather_dashboard(airport, target_date, nws_value, om_value, mean)

        return mean

    def _fetch_open_meteo(self, airport: Airport, target_date: dt.date) -> dict[str, Any] | None:
        if self._open_meteo_client is None:
            return None
        try:
            return self._open_meteo_client.get_forecast_for_date(airport.lat, airport.lon, target_date)
        except Exception:
            logger.debug("Open-Meteo forecast fetch failed for %s", airport.code, exc_info=True)
            return None

    # --- Threshold-phrased markets (rain/snow, "exceed X degrees") ---

    def _process_threshold_market(self, spec: WeatherMarketSpec) -> None:
        airport = AIRPORTS.get(spec.location)

        periods = self._weather_client.get_forecast_for_date(spec.lat, spec.lon, spec.target_date)
        if not periods:
            logger.debug("No NWS forecast available yet for %s on %s", spec.location, spec.target_date)
            return

        open_meteo_forecast = self._fetch_open_meteo(airport, spec.target_date) if airport else None

        signal = generate_signal(spec, periods, self._min_edge, open_meteo_forecast)

        if airport is not None:
            self._record_market_dashboard(
                airport, spec.market_slug,
                {
                    "type": spec.variable,
                    "question": spec.question,
                    "target_date": spec.target_date.isoformat(),
                    "threshold": spec.threshold,
                    "market_yes_price": spec.yes_price,
                    "estimated_probability": signal.estimated_probability if signal else None,
                    "edge": signal.edge if signal else None,
                    "side": signal.side if signal else None,
                },
            )

        if signal is None:
            return

        if airport is not None:
            self._record_history(airport, signal, market_type=spec.variable)
        self._trader.execute(signal)

    # --- Dashboard recording (no-ops if no DashboardState configured) ---

    def _record_weather_dashboard(
        self, airport: Airport, target_date: dt.date, nws_value: float | None, om_value: float | None, mean: float
    ) -> None:
        if self._dashboard_state is None:
            return
        self._dashboard_state.update_weather(
            airport.code,
            {
                "airport_name": airport.name,
                "target_date": target_date.isoformat(),
                "nws_forecast": nws_value,
                "open_meteo_forecast": om_value,
                "blended_forecast": mean,
            },
        )

    def _record_market_dashboard(self, airport: Airport, market_slug: str, entry: dict[str, Any]) -> None:
        if self._dashboard_state is None:
            return
        self._dashboard_state.update_market(airport.code, market_slug, entry)

    def _record_history(self, airport: Airport, signal: TradeSignal, market_type: str) -> None:
        if self._dashboard_state is None:
            return
        self._dashboard_state.record_history(
            {
                "airport": airport.code,
                "market_slug": signal.market.market_slug,
                "question": signal.market.question,
                "type": market_type,
                "side": signal.side,
                "estimated_probability": signal.estimated_probability,
                "market_probability": signal.market_probability,
                "edge": signal.edge,
            }
        )

    # --- Diagnostics (unchanged from the discovery-access investigation) ---

    def _log_discovery_diagnostics(self, markets: list[dict[str, Any]]) -> None:
        """One-time (per process) dump of the real category taxonomy and
        any loosely-weather-looking markets, independent of
        is_weather_market()'s verdict - lets us tell "no weather markets
        exist right now" apart from "the filter is wrong about what a
        weather market looks like" using real production data."""
        if self._logged_discovery_diagnostics:
            return
        self._logged_discovery_diagnostics = True

        categories = Counter(str(m.get("category") or "<none>") for m in markets)
        logger.info("DIAGNOSTIC category breakdown (top 20 of %d markets): %s", len(markets), categories.most_common(20))

        dumped = 0
        loose_matches = 0
        for m in markets:
            text = f"{m.get('question', '')} {m.get('slug', '')}".lower()
            if any(term in text for term in _LOOSE_DIAGNOSTIC_TERMS):
                loose_matches += 1
                if dumped < _MAX_LOOSE_DIAGNOSTIC_DUMPS:
                    dumped += 1
                    logger.info(
                        "DIAGNOSTIC loose-text candidate (%d/%d): %s",
                        dumped,
                        _MAX_LOOSE_DIAGNOSTIC_DUMPS,
                        json.dumps(m, default=str)[:3000],
                    )
        logger.info("DIAGNOSTIC loose-text scan: %d candidate(s) out of %d markets", loose_matches, len(markets))

        try:
            probe_results = self._us_client.probe_categories(_CATEGORY_PROBE_CANDIDATES)
            logger.info("DIAGNOSTIC explicit category probe: %s", probe_results)
        except Exception:
            logger.exception("DIAGNOSTIC category probe failed")

        if self._diagnostic_probe_slug:
            market = self._us_client.retrieve_market_by_slug(self._diagnostic_probe_slug)
            if market is None:
                logger.info(
                    "DIAGNOSTIC slug probe: '%s' NOT FOUND/inaccessible via this API key",
                    self._diagnostic_probe_slug,
                )
            else:
                logger.info(
                    "DIAGNOSTIC slug probe: '%s' FOUND - %s",
                    self._diagnostic_probe_slug,
                    json.dumps(market, default=str)[:3000],
                )

    def _log_diagnostic_sample(self, market: dict[str, Any]) -> None:
        if self._diagnostic_dumps >= _MAX_DIAGNOSTIC_DUMPS:
            return
        self._diagnostic_dumps += 1
        logger.info(
            "DIAGNOSTIC (%d/%d): could not parse a weather spec, raw market data: %s",
            self._diagnostic_dumps,
            _MAX_DIAGNOSTIC_DUMPS,
            json.dumps(market, default=str)[:4000],
        )
