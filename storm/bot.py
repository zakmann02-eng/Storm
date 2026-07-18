"""Orchestrates one scan-and-trade cycle: discover markets, filter to
weather, parse, pull a forecast, and hand any signal to the trader.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from storm.gamma_client import GammaClient, parse_outcome_prices
from storm.market_filter import is_weather_market
from storm.market_parser import parse_weather_market
from storm.risk_manager import RiskManager
from storm.signal_engine import generate_signal
from storm.trader import Trader
from storm.weather_client import NWSClient

logger = logging.getLogger(__name__)


class StormBot:
    def __init__(
        self,
        gamma_client: GammaClient,
        weather_client: NWSClient,
        trader: Trader,
        risk_manager: RiskManager,
        min_edge: float,
    ):
        self._gamma_client = gamma_client
        self._weather_client = weather_client
        self._trader = trader
        self._risk_manager = risk_manager
        self._min_edge = min_edge

    def run_cycle(self) -> None:
        if os.getenv("PAUSED", "false").lower() == "true":
            logger.info("Bot paused - skipping scan")
            return

        markets = list(self._gamma_client.iter_active_markets())
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

    def _process_market(self, market: dict[str, Any]) -> None:
        condition_id = market.get("conditionId", "")
        if condition_id and self._risk_manager.already_traded(condition_id):
            logger.debug("Already traded %s today - skipping", condition_id)
            return

        market_slug = market.get("slug") or ""
        prices = parse_outcome_prices(market)
        # Binary Polymarket markets list outcome prices as [Yes, No].
        if not market_slug or len(prices) != 2:
            logger.debug("Skipping %s: missing slug/prices", market.get("slug"))
            return

        yes_price = prices[0]

        spec = parse_weather_market(market, market_slug, yes_price)
        if spec is None:
            logger.debug("Could not parse a weather spec from: %s", market.get("question"))
            return

        periods = self._weather_client.get_forecast_for_date(spec.lat, spec.lon, spec.target_date)
        if not periods:
            logger.debug("No NWS forecast available yet for %s on %s", spec.location, spec.target_date)
            return

        signal = generate_signal(spec, periods, self._min_edge)
        if signal is None:
            return

        self._trader.execute(signal)
