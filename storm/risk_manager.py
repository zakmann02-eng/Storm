"""Hard trading limits for Storm: pause/kill-switch checks plus
position/session caps, matching Colossus's MIN_TRADE_USD/MAX_TRADE_USD/
MAX_TRADES_SESSION semantics, plus a Storm-only daily $ cap. State
persists to disk (mirroring Colossus's daily_count.json) so caps survive
restarts, and every method is lock-protected since Storm's Telegram
command listener runs on its own thread alongside the main scan loop.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILE = Path("storm_daily_state.json")


def file_kill_switch(path: str) -> Callable[[], bool]:
    """A kill switch that trips as soon as a flag file appears on disk -
    no redeploy/restart or Telegram access needed, unlike PAUSED."""

    def check() -> bool:
        return os.path.exists(path)

    return check


def _paused_env() -> bool:
    return os.getenv("PAUSED", "false").strip().lower() == "true"


class RiskManager:
    def __init__(
        self,
        min_trade_usd: float,
        max_trade_usd: float,
        max_trades_session: int,
        max_daily_spend_usdc: float,
        kill_switch_check: Callable[[], bool] | None = None,
        paused_check: Callable[[], bool] | None = None,
        state_file: Path = DEFAULT_STATE_FILE,
    ):
        self._min_trade = min_trade_usd
        self._max_trade = max_trade_usd
        self._max_trades_session = max_trades_session
        self._max_daily_spend = max_daily_spend_usdc
        self._kill_switch_check = kill_switch_check or (lambda: False)
        self._paused_check = paused_check or _paused_env
        self._state_file = state_file
        self._lock = threading.Lock()

        self._current_day: date | None = None
        self._spent_today = 0.0
        self._traded_condition_ids: set[str] = set()
        self._trades_today: list[dict] = []
        self._load()

    # --- persistence ---

    def _load(self) -> None:
        self._current_day = datetime.now(timezone.utc).date()
        if not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text())
            if data.get("date") == str(self._current_day):
                self._spent_today = float(data.get("spent_today", 0.0))
                self._traded_condition_ids = set(data.get("traded_condition_ids", []))
                self._trades_today = list(data.get("trades", []))
        except Exception:
            logger.exception("Could not load %s - starting with a clean daily state", self._state_file)

    def _save_locked(self) -> None:
        try:
            self._state_file.write_text(json.dumps({
                "date": str(self._current_day),
                "spent_today": self._spent_today,
                "traded_condition_ids": sorted(self._traded_condition_ids),
                "trades": self._trades_today,
            }))
        except Exception:
            logger.exception("Could not save %s", self._state_file)

    def _roll_day_locked(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._current_day:
            self._current_day = today
            self._spent_today = 0.0
            self._traded_condition_ids = set()
            self._trades_today = []

    # --- checks ---

    def kill_switch_active(self) -> bool:
        return self._paused_check() or self._kill_switch_check()

    def already_traded(self, condition_id: str) -> bool:
        with self._lock:
            self._roll_day_locked()
            return condition_id in self._traded_condition_ids

    def size_order(self, requested_usdc: float) -> float:
        """Return the USDC size actually allowed for this order, or 0.0 if
        the trade must be skipped entirely (paused, over a cap, or below
        the minimum trade floor)."""
        if self.kill_switch_active():
            logger.warning("Kill switch/pause active - skipping trade")
            return 0.0

        if requested_usdc <= 0:
            return 0.0

        with self._lock:
            self._roll_day_locked()

            if len(self._trades_today) >= self._max_trades_session:
                logger.info("Session trade cap of %d reached - skipping trade", self._max_trades_session)
                return 0.0

            remaining_daily = self._max_daily_spend - self._spent_today
            if remaining_daily <= 0:
                logger.info("Daily spend cap of %.2f reached - skipping trade", self._max_daily_spend)
                return 0.0

            size = min(requested_usdc, self._max_trade, remaining_daily)
            if size < self._min_trade:
                logger.info("Sized trade $%.2f below MIN_TRADE_USD=$%.2f - skipping", size, self._min_trade)
                return 0.0
            return size

    def record_trade(self, condition_id: str, usdc_amount: float, summary: dict) -> None:
        with self._lock:
            self._roll_day_locked()
            self._spent_today += usdc_amount
            if condition_id:
                self._traded_condition_ids.add(condition_id)
            self._trades_today.append(summary)
            self._save_locked()

    def trades_today(self) -> list[dict]:
        with self._lock:
            self._roll_day_locked()
            return list(self._trades_today)

    def spent_today(self) -> float:
        with self._lock:
            self._roll_day_locked()
            return self._spent_today
