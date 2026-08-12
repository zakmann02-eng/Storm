"""Thread-safe shared state for the dashboard.

Storm's scan loop (main thread) writes to this every cycle; the dashboard
HTTP server (its own background thread, like the Telegram command
listener) reads from it to serve the API. Every method takes the lock -
callers never touch the internal dicts directly, and snapshot() returns
copies so a reader can't be affected by an in-progress write.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DashboardState:
    def __init__(self, history_limit: int = 200):
        self._lock = threading.Lock()
        self._weather: dict[str, dict[str, Any]] = {}
        self._markets: dict[str, dict[str, dict[str, Any]]] = {}
        self._history: deque[dict[str, Any]] = deque(maxlen=history_limit)
        self._last_scan_at: str | None = None
        self._last_scan_summary: dict[str, Any] = {}

    def update_weather(self, airport_code: str, forecast: dict[str, Any]) -> None:
        with self._lock:
            self._weather[airport_code] = {**forecast, "updated_at": _now_iso()}

    def update_market(self, airport_code: str, market_slug: str, entry: dict[str, Any]) -> None:
        with self._lock:
            self._markets.setdefault(airport_code, {})[market_slug] = {**entry, "updated_at": _now_iso()}

    def record_history(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._history.appendleft({**entry, "recorded_at": _now_iso()})

    def record_scan_summary(self, total_markets: int, weather_related: int) -> None:
        with self._lock:
            self._last_scan_at = _now_iso()
            self._last_scan_summary = {"total_markets": total_markets, "weather_related": weather_related}

    def snapshot(self) -> dict[str, Any]:
        """Thread-safe read of the full state, for the dashboard API."""
        with self._lock:
            return {
                "last_scan_at": self._last_scan_at,
                "last_scan_summary": dict(self._last_scan_summary),
                "weather": {code: dict(forecast) for code, forecast in self._weather.items()},
                "markets": {
                    code: {slug: dict(entry) for slug, entry in markets.items()}
                    for code, markets in self._markets.items()
                },
                "history": list(self._history),
            }
