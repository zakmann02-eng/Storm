"""Hard trading limits for Storm: a kill switch and position/daily spend
caps. These are Storm's own limits, tracked independently of Colossus -
Storm only knows about the USDC it spends itself.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)


def file_kill_switch(path: str) -> Callable[[], bool]:
    """A kill switch that trips as soon as a flag file appears on disk -
    no redeploy/restart needed, unlike an env-var-only switch."""

    def check() -> bool:
        return os.path.exists(path)

    return check


class RiskManager:
    def __init__(
        self,
        max_position_usdc: float,
        max_daily_spend_usdc: float,
        kill_switch_env: bool = False,
        kill_switch_check: Callable[[], bool] | None = None,
    ):
        self._max_position = max_position_usdc
        self._max_daily_spend = max_daily_spend_usdc
        self._kill_switch_env = kill_switch_env
        self._kill_switch_check = kill_switch_check or (lambda: False)
        self._spent_today = 0.0
        self._current_day = None

    def _roll_day(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._current_day:
            self._current_day = today
            self._spent_today = 0.0

    def kill_switch_active(self) -> bool:
        return self._kill_switch_env or self._kill_switch_check()

    def size_order(self, requested_usdc: float) -> float:
        """Return the USDC size actually allowed for this order, reduced to
        fit remaining caps, or 0.0 if the trade must be skipped entirely."""
        if self.kill_switch_active():
            logger.warning("Kill switch active - skipping trade")
            return 0.0

        if requested_usdc <= 0:
            return 0.0

        self._roll_day()
        remaining_daily = self._max_daily_spend - self._spent_today
        if remaining_daily <= 0:
            logger.info("Daily spend cap of %.2f reached - skipping trade", self._max_daily_spend)
            return 0.0

        return max(min(requested_usdc, self._max_position, remaining_daily), 0.0)

    def record_spend(self, usdc_amount: float) -> None:
        self._roll_day()
        self._spent_today += usdc_amount
