"""Thin wrapper around the polymarket-us SDK (PolymarketUS) - the actual
trading API for Polymarket.US, and the one Colossus already uses on this
same account. Every call is rate-limited since it hits the same shared
account/key as Colossus.

Order construction mirrors Colossus's polymarket_client.py exactly so the
two bots behave identically against the exchange.
"""

from __future__ import annotations

import logging

from storm.rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger(__name__)


def _extract_events(data: object) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("data") or data.get("events") or data.get("results") or []
    return []


def _flatten_events(events: list[dict]) -> list[dict]:
    """Polymarket groups related outcomes under one event (e.g. a single
    "Highest temperature in NYC" event containing several range-bucket
    sub-markets like "78 or below", "79 to 80", ...). Flatten each
    sub-market into its own dict, merged with the parent event's shared
    fields (category, tags, endDate), mirroring Colossus's own
    event-flattening in _get_us_sdk_markets."""
    markets: list[dict] = []
    for event in events:
        event_slug = event.get("slug") or event.get("eventSlug") or ""
        sub_markets = event.get("markets") or []
        if sub_markets:
            for m in sub_markets:
                row = {**event, **m}
                row["eventSlug"] = event_slug
                row["question"] = (
                    m.get("question") or m.get("title") or event.get("title") or event.get("question") or ""
                )
                markets.append(row)
        else:
            row = dict(event)
            row["eventSlug"] = event_slug
            row["question"] = event.get("question") or event.get("title") or ""
            markets.append(row)
    return markets


class USClient:
    def __init__(self, key_id: str, secret_key: str, rate_limiter: TokenBucketRateLimiter):
        self._rate_limiter = rate_limiter
        self._client = self._init_client(key_id, secret_key)

    def _init_client(self, key_id: str, secret_key: str):
        from polymarket_us import PolymarketUS

        client = PolymarketUS(key_id=key_id.strip(), secret_key=secret_key.strip())
        logger.info("Polymarket.US client initialized - key_id %s...", key_id.strip()[:8])
        return client

    def list_events(self, limit: int = 200, max_pages: int = 15) -> list[dict]:
        """Storm's primary market-discovery source. Polymarket.US's own
        markets (including the "Temp" weather category) don't appear to
        be served by the generic public Gamma API - Colossus already
        relies on this same SDK call as its primary source for the same
        reason, only falling back to Gamma when this fails."""
        all_markets: list[dict] = []
        offset = 0
        for _ in range(max_pages):
            self._rate_limiter.acquire()
            try:
                data = self._client.events.list({"limit": limit, "active": True, "offset": offset})
            except Exception:
                logger.exception("events.list failed at offset %d", offset)
                break

            events = _extract_events(data)
            if not events:
                break

            all_markets.extend(_flatten_events(events))
            if len(events) < limit:
                break
            offset += limit

        return all_markets

    def get_balance(self) -> float:
        self._rate_limiter.acquire()
        try:
            data = self._client.account.balances()
        except Exception:
            logger.exception("get_balance failed - returning 0 to prevent unsafe trades")
            return 0.0

        if not isinstance(data, dict):
            return 0.0
        balances = data.get("balances")
        if balances and isinstance(balances, list):
            b = balances[0]
            return float(b.get("buyingPower") or b.get("currentBalance") or 0)
        return float(data.get("cash") or data.get("balance") or data.get("availableBalance") or 0)

    def place_order(self, market_slug: str, side: str, price: float, amount_usd: float) -> dict | None:
        """side: 'YES' or 'NO'. `price` is the YES-side market probability;
        for NO orders it's converted to the NO-token price, same as
        Colossus does."""
        from polymarket_us import AuthenticationError, BadRequestError, NotFoundError

        intent = "ORDER_INTENT_BUY_LONG" if side == "YES" else "ORDER_INTENT_BUY_SHORT"
        order_price = round(price, 4) if side == "YES" else round(1.0 - price, 4)
        order_price = max(0.01, min(0.99, order_price))
        quantity = max(1, round(amount_usd / order_price))
        order = {
            "marketSlug": market_slug,
            "intent": intent,
            "type": "ORDER_TYPE_LIMIT",
            "price": {"value": str(order_price), "currency": "USD"},
            "quantity": quantity,
            "tif": "TIME_IN_FORCE_GOOD_TILL_CANCEL",
        }

        self._rate_limiter.acquire()
        logger.info("Placing order: %s", order)
        try:
            return self._client.orders.create(order)
        except AuthenticationError as exc:
            logger.error("Auth error placing order for %s: %s", market_slug, exc)
        except BadRequestError as exc:
            logger.error("Bad request placing order for %s: %s | payload=%s", market_slug, exc, order)
        except NotFoundError as exc:
            logger.error("Market not found (%s): %s", market_slug, exc)
        except Exception:
            logger.exception("Order error for %s | payload=%s", market_slug, order)
        return None
