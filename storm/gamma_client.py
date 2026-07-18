"""Client for Polymarket's public Gamma Markets API (market discovery).

Gamma is read-only and keyless, but Storm still routes every call through
the shared rate limiter since it's the same underlying Polymarket account
as Colossus and we want one ceiling covering all outbound traffic.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterator

import requests

from storm.rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger(__name__)


class GammaClient:
    def __init__(
        self,
        base_url: str,
        rate_limiter: TokenBucketRateLimiter,
        session: requests.Session | None = None,
        timeout: float = 10.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._rate_limiter = rate_limiter
        self._session = session or requests.Session()
        self._timeout = timeout

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self._rate_limiter.acquire()
        resp = self._session.get(f"{self._base_url}{path}", params=params, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def list_markets_page(self, limit: int = 500, offset: int = 0) -> list[dict[str, Any]]:
        return self._get(
            "/markets",
            params={
                "active": "true",
                "closed": "false",
                "archived": "false",
                "limit": limit,
                "offset": offset,
            },
        )

    def iter_active_markets(self, page_size: int = 500) -> Iterator[dict[str, Any]]:
        offset = 0
        while True:
            page = self.list_markets_page(limit=page_size, offset=offset)
            if not page:
                return
            yield from page
            if len(page) < page_size:
                return
            offset += page_size


def parse_clob_token_ids(market: dict[str, Any]) -> list[str]:
    """clobTokenIds is returned by Gamma as a JSON-stringified list."""
    raw = market.get("clobTokenIds")
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    return json.loads(raw)


def parse_outcome_prices(market: dict[str, Any]) -> list[float]:
    """outcomePrices is returned by Gamma as a JSON-stringified list of strings."""
    raw = market.get("outcomePrices")
    if not raw:
        return []
    values = raw if isinstance(raw, list) else json.loads(raw)
    return [float(v) for v in values]
