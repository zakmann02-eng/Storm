"""Client for the National Weather Service API (api.weather.gov).

Free and keyless, but NWS's usage policy asks for an identifying
User-Agent on every request. This is a separate data source from
Polymarket entirely, so it is not subject to Storm's Polymarket rate
limiter - only to its own light in-process caching.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

NWS_BASE_URL = "https://api.weather.gov"


def period_date(period: dict[str, Any]) -> dt.date:
    return dt.datetime.fromisoformat(period["startTime"]).date()


class NWSClient:
    def __init__(self, user_agent: str, session: requests.Session | None = None, timeout: float = 10.0):
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": user_agent, "Accept": "application/geo+json"})
        self._timeout = timeout
        self._point_cache: dict[tuple[float, float], dict[str, Any]] = {}

    def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        resp = self._session.get(url, params=params, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def _get_point(self, lat: float, lon: float) -> dict[str, Any]:
        key = (round(lat, 4), round(lon, 4))
        if key not in self._point_cache:
            self._point_cache[key] = self._get(f"{NWS_BASE_URL}/points/{key[0]},{key[1]}")
        return self._point_cache[key]

    def get_forecast_periods(self, lat: float, lon: float) -> list[dict[str, Any]]:
        """12-hour day/night forecast periods, each with `temperature`,
        `isDaytime`, and `probabilityOfPrecipitation` (when applicable)."""
        point = self._get_point(lat, lon)
        forecast_url = point["properties"]["forecast"]
        data = self._get(forecast_url)
        return data["properties"]["periods"]

    def get_forecast_for_date(self, lat: float, lon: float, target_date: dt.date) -> list[dict[str, Any]]:
        periods = self.get_forecast_periods(lat, lon)
        return [p for p in periods if period_date(p) == target_date]
