"""Orchestrates one scan-and-trade cycle: discover markets, filter to
weather, parse, pull a forecast, and hand any signal to the trader.
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from typing import Any

from storm.gamma_client import GammaClient, parse_outcome_prices
from storm.market_filter import is_weather_market
from storm.market_parser import parse_weather_market
from storm.openmeteo_client import OpenMeteoClient
from storm.risk_manager import RiskManager
from storm.signal_engine import generate_signal
from storm.trader import Trader
from storm.us_client import USClient
from storm.weather_client import NWSClient

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
    ):
        self._us_client = us_client
        self._gamma_client = gamma_client
        self._weather_client = weather_client
        self._open_meteo_client = open_meteo_client
        self._trader = trader
        self._risk_manager = risk_manager
        self._min_edge = min_edge
        self._diagnostic_dumps = 0
        self._logged_discovery_diagnostics = False

    def run_cycle(self) -> None:
        if os.getenv("PAUSED", "false").lower() == "true":
            logger.info("Bot paused - skipping scan")
            return

        markets = self._discover_markets()
        self._log_discovery_diagnostics(markets)
        weather_markets = [m for m in markets if is_weather_market(m)]
        logger.info("Scanned %d active markets, %d look weather-related", len(markets), len(weather_markets))

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
            logger.warning("polymarket-us markets.list() returned no markets - falling back to Gamma API")
        except Exception:
            logger.exception("polymarket-us markets.list() failed - falling back to Gamma API")
        return list(self._gamma_client.iter_active_markets())

    def _process_market(self, market: dict[str, Any]) -> None:
        condition_id = market.get("conditionId", "")
        if condition_id and self._risk_manager.already_traded(condition_id):
            logger.debug("Already traded %s today - skipping", condition_id)
            return

        market_slug = market.get("slug") or ""
        prices = parse_outcome_prices(market)
        # Binary Polymarket markets (including each individual range-bucket
        # outcome within a grouped event) list outcome prices as [Yes, No].
        if not market_slug or len(prices) != 2:
            logger.debug("Skipping %s: missing slug/prices", market.get("slug"))
            return

        yes_price = prices[0]

        spec = parse_weather_market(market, market_slug, yes_price)
        if spec is None:
            self._log_diagnostic_sample(market)
            return

        periods = self._weather_client.get_forecast_for_date(spec.lat, spec.lon, spec.target_date)
        if not periods:
            logger.debug("No NWS forecast available yet for %s on %s", spec.location, spec.target_date)
            return

        open_meteo_forecast = self._get_open_meteo_forecast(spec)

        signal = generate_signal(spec, periods, self._min_edge, open_meteo_forecast)
        if signal is None:
            return

        self._trader.execute(signal)

    def _get_open_meteo_forecast(self, spec) -> dict[str, Any] | None:
        """Best-effort second forecast source for a small ensemble -
        Open-Meteo failing or being unconfigured just falls back to
        NWS-only, it's never required."""
        if self._open_meteo_client is None:
            return None
        try:
            return self._open_meteo_client.get_forecast_for_date(spec.lat, spec.lon, spec.target_date)
        except Exception:
            logger.debug("Open-Meteo forecast fetch failed for %s", spec.location, exc_info=True)
            return None

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
