"""Background thread that long-polls Telegram for incoming commands
(/status, /pause, /resume, /report), the same command set Colossus
supports, so Storm can be controlled the same way without pulling in an
async framework.

Runs alongside the main synchronous scan loop on its own daemon thread;
RiskManager is lock-protected so both threads can read/write it safely.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from storm.risk_manager import RiskManager
from storm.telegram_bot import TelegramNotifier

logger = logging.getLogger(__name__)


class TelegramCommandListener(threading.Thread):
    def __init__(
        self,
        notifier: TelegramNotifier,
        risk_manager: RiskManager,
        live_trading: bool,
        max_trade_usd: float,
        max_trades_session: int,
        max_daily_spend_usdc: float,
        min_edge: float,
    ):
        super().__init__(daemon=True, name="storm-telegram-commands")
        self._notifier = notifier
        self._risk_manager = risk_manager
        self._live_trading = live_trading
        self._max_trade_usd = max_trade_usd
        self._max_trades_session = max_trades_session
        self._max_daily_spend_usdc = max_daily_spend_usdc
        self._min_edge = min_edge
        self._offset: int | None = None
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        if not self._notifier.enabled:
            logger.info("Telegram not configured - command listener not started")
            return
        logger.info("Telegram command listener starting")
        while not self._stop_event.is_set():
            try:
                updates = self._notifier.get_updates(self._offset)
            except Exception:
                logger.exception("Telegram getUpdates failed - retrying in 5s")
                time.sleep(5)
                continue
            for update in updates:
                self._offset = update["update_id"] + 1
                message = update.get("message") or {}
                text = (message.get("text") or "").strip()
                if text.startswith("/"):
                    self._handle_command(text)

    def _handle_command(self, text: str) -> None:
        command = text.split()[0].lower().split("@")[0]
        if command == "/status":
            self._notifier.send(self._status_text())
        elif command == "/pause":
            os.environ["PAUSED"] = "true"
            self._notifier.send("Storm paused.")
        elif command == "/resume":
            os.environ["PAUSED"] = "false"
            self._notifier.send("Storm resumed.")
        elif command == "/report":
            self._notifier.send(self._report_text())

    def _status_text(self) -> str:
        paused = os.getenv("PAUSED", "false").lower() == "true"
        trades = self._risk_manager.trades_today()
        return (
            "Storm Status\n"
            f"Paused: {'yes' if paused else 'no'}\n"
            f"Live trading: {'yes' if self._live_trading else 'no (dry-run)'}\n"
            f"Trades today: {len(trades)}/{self._max_trades_session}\n"
            f"Spent today: ${self._risk_manager.spent_today():.2f} / ${self._max_daily_spend_usdc:.2f}\n"
            f"Trade size cap: ${self._max_trade_usd:.2f}\n"
            f"Min edge: {self._min_edge:.2f}"
        )

    def _report_text(self) -> str:
        trades = self._risk_manager.trades_today()
        if not trades:
            return "No trades recorded today."
        lines = [f"Storm Daily Report - {len(trades)} trade(s)\n"]
        for t in trades[-20:]:
            lines.append(f"{t['side']} {t['question'][:50]} @ {t['price']:.3f} for ${t['usdc']:.2f}")
        return "\n".join(lines)
