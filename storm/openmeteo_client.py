"""Client for Open-Meteo's free, keyless weather forecast API.

Blended with NWS in signal_engine.py rather than used alone: Open-Meteo's
default ("best_match") response already blends multiple weather models
(GFS, ECMWF, ICON, ...) - averaging its estimate with NWS's own gives
Storm a small ensemble instead of relying on a single model's point
forecast, the same approach other Polymarket weather bots use.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

OPEN_METEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"


class OpenMeteoClient:
    def __init__(self, session: requests.Session | None = None, timeout: float = 10.0):
        self._session = session or requests.Session()
        self._timeout = timeout

    def get_daily_forecast(self, lat: float, lon: float, forecast_days: int = 10) -> dict[str, dict[str, Any]]:
        """Daily max/min temperature (F) and max precipitation probability,
        keyed by ISO date string ("2026-07-20")."""
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "temperature_unit": "fahrenheit",
            "timezone": "auto",
            "forecast_days": forecast_days,
        }
        resp = self._session.get(OPEN_METEO_BASE_URL, params=params, timeout=self._timeout)
        resp.raise_for_status()
        daily = resp.json().get("daily", {})

        dates = daily.get("time", [])
        highs = daily.get("temperature_2m_max", [])
        lows = daily.get("temperature_2m_min", [])
        pops = daily.get("precipitation_probability_max", [])

        by_date: dict[str, dict[str, Any]] = {}
        for i, date_str in enumerate(dates):
            by_date[date_str] = {
                "temperature_max": highs[i] if i < len(highs) else None,
                "temperature_min": lows[i] if i < len(lows) else None,
                "precipitation_probability_max": pops[i] if i < len(pops) else None,
            }
        return by_date

    def get_forecast_for_date(self, lat: float, lon: float, target_date: dt.date) -> dict[str, Any] | None:
        by_date = self.get_daily_forecast(lat, lon)
        return by_date.get(target_date.isoformat())
