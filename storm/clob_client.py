"""Thin wrapper around py-clob-client that funnels every call through
Storm's rate limiter, since it hits the same Polymarket account/key as
Colossus.
"""

from __future__ import annotations

import logging

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

from storm.rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger(__name__)


def build_clob_client(
    host: str,
    chain_id: int,
    private_key: str,
    funder: str,
    api_key: str = "",
    api_secret: str = "",
    api_passphrase: str = "",
) -> ClobClient:
    client = ClobClient(
        host,
        key=private_key,
        chain_id=chain_id,
        signature_type=1,
        funder=funder,
    )
    if api_key and api_secret and api_passphrase:
        creds = ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase)
    else:
        creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    return client


class RateLimitedClobClient:
    def __init__(self, client: ClobClient, rate_limiter: TokenBucketRateLimiter):
        self._client = client
        self._rate_limiter = rate_limiter

    def get_price(self, token_id: str, side: str) -> float:
        self._rate_limiter.acquire()
        resp = self._client.get_price(token_id=token_id, side=side)
        return float(resp["price"])

    def get_midpoint(self, token_id: str) -> float:
        self._rate_limiter.acquire()
        resp = self._client.get_midpoint(token_id=token_id)
        return float(resp["mid"])

    def place_limit_order(self, token_id: str, price: float, size: float, side: str) -> dict:
        """side: 'BUY' or 'SELL'. Places a GTC limit order and returns the
        exchange's response."""
        order_side = BUY if side == "BUY" else SELL
        order_args = OrderArgs(token_id=token_id, price=price, size=size, side=order_side)

        self._rate_limiter.acquire()
        signed_order = self._client.create_order(order_args)

        self._rate_limiter.acquire()
        return self._client.post_order(signed_order, OrderType.GTC)
