"""Turns a TradeSignal into either a dry-run log line or a real CLOB order,
subject to RiskManager's caps and Storm's LIVE_TRADING switch.

Storm defaults to dry-run (LIVE_TRADING=false) so it can run safely in
production and log what it *would* trade before anyone flips it live.
"""

from __future__ import annotations

import logging

from storm.clob_client import RateLimitedClobClient
from storm.risk_manager import RiskManager
from storm.signal_engine import TradeSignal

logger = logging.getLogger(__name__)


class Trader:
    def __init__(
        self,
        clob_client: RateLimitedClobClient | None,
        risk_manager: RiskManager,
        live_trading: bool,
        default_order_usdc: float,
    ):
        self._clob_client = clob_client
        self._risk_manager = risk_manager
        self._live_trading = live_trading
        self._default_order_usdc = default_order_usdc

    def execute(self, signal: TradeSignal) -> None:
        spec = signal.market
        price = signal.market_probability
        if price <= 0 or price >= 1:
            logger.info("Skipping %s: unusable price %.4f", spec.question, price)
            return

        approved_usdc = self._risk_manager.size_order(self._default_order_usdc)
        if approved_usdc <= 0:
            logger.info("Skipping %s (%s): risk manager declined the trade", spec.question, signal.side)
            return

        size_shares = round(approved_usdc / price, 2)
        token_id = spec.yes_token_id if signal.side == "YES" else spec.no_token_id

        if not self._live_trading:
            logger.info(
                "[DRY RUN] Would BUY %.2f shares of '%s' @ %.4f (%s, edge=%.3f, "
                "est_prob=%.3f) for ~$%.2f",
                size_shares,
                spec.question,
                price,
                signal.side,
                signal.edge,
                signal.estimated_probability,
                approved_usdc,
            )
            return

        if self._clob_client is None:
            logger.error("LIVE_TRADING is enabled but no CLOB client is configured - skipping order")
            return

        logger.info(
            "Placing LIVE order: BUY %.2f shares of '%s' @ %.4f (%s, edge=%.3f) for ~$%.2f",
            size_shares,
            spec.question,
            price,
            signal.side,
            signal.edge,
            approved_usdc,
        )
        response = self._clob_client.place_limit_order(token_id, price, size_shares, "BUY")
        logger.info("Order response: %s", response)
        self._risk_manager.record_spend(approved_usdc)
