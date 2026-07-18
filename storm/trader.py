"""Turns a TradeSignal into either a dry-run log line or a real order via
the Polymarket.US SDK, subject to RiskManager's caps and Storm's
LIVE_TRADING switch. Sends a Telegram alert (if configured) either way, and
records the trade in RiskManager so daily caps/session count/dedup stay
accurate whether or not the order was real.

Storm defaults to dry-run (LIVE_TRADING=false) so it can run safely in
production and log what it *would* trade before anyone flips it live.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from storm.risk_manager import RiskManager
from storm.signal_engine import TradeSignal
from storm.telegram_bot import TelegramNotifier
from storm.us_client import USClient

logger = logging.getLogger(__name__)


class Trader:
    def __init__(
        self,
        us_client: USClient | None,
        risk_manager: RiskManager,
        notifier: TelegramNotifier | None,
        live_trading: bool,
        default_order_usdc: float,
    ):
        self._us_client = us_client
        self._risk_manager = risk_manager
        self._notifier = notifier
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

        summary = {
            "time": datetime.now(timezone.utc).isoformat(),
            "market_slug": spec.market_slug,
            "question": spec.question,
            "side": signal.side,
            "price": price,
            "usdc": approved_usdc,
            "edge": signal.edge,
            "estimated_probability": signal.estimated_probability,
        }

        if not self._live_trading:
            logger.info(
                "[DRY RUN] Would BUY '%s' @ %.4f (%s, edge=%.3f, est_prob=%.3f) for ~$%.2f",
                spec.market_slug,
                price,
                signal.side,
                signal.edge,
                signal.estimated_probability,
                approved_usdc,
            )
            self._risk_manager.record_trade(spec.condition_id, approved_usdc, summary)
            self._notify(
                f"[DRY RUN] Storm signal\n{spec.question[:120]}\n"
                f"Side: {signal.side} @ {price:.3f}\nSize: ${approved_usdc:.2f}\n"
                f"Edge: {signal.edge:+.1%}  Est. prob: {signal.estimated_probability:.1%}"
            )
            return

        if self._us_client is None:
            logger.error("LIVE_TRADING is enabled but no Polymarket.US client is configured - skipping order")
            return

        logger.info(
            "Placing LIVE order: BUY '%s' @ %.4f (%s, edge=%.3f) for ~$%.2f",
            spec.market_slug,
            price,
            signal.side,
            signal.edge,
            approved_usdc,
        )
        response = self._us_client.place_order(spec.market_slug, signal.side, price, approved_usdc)
        logger.info("Order response: %s", response)

        self._risk_manager.record_trade(spec.condition_id, approved_usdc, summary)
        self._notify(
            f"Storm trade opened\n{spec.question[:120]}\n"
            f"Side: {signal.side} @ {price:.3f}\nSize: ${approved_usdc:.2f}\n"
            f"Edge: {signal.edge:+.1%}  Est. prob: {signal.estimated_probability:.1%}"
        )

    def _notify(self, text: str) -> None:
        if self._notifier is not None:
            self._notifier.send(text)
