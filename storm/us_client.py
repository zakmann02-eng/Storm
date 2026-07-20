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


def _extract_items(data: object, *keys: str) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            if data.get(key):
                return data[key]
    return []


def _flatten_grouped(items: list[dict]) -> list[dict]:
    """Polymarket sometimes groups related outcomes under one parent (e.g.
    a single "Highest temperature in NYC" event containing several
    range-bucket sub-markets like "78 or below", "79 to 80", ...) and
    sometimes returns already-flat individual markets. Handle both: flatten
    any nested "markets" sub-array into its own row merged with the
    parent's shared fields, normalizing a "question" text field either way
    ("title" is the polymarket-us SDK's field name; Gamma uses "question")."""
    rows: list[dict] = []
    for item in items:
        item_slug = item.get("eventSlug") or item.get("slug") or ""
        sub_markets = item.get("markets") or []
        if sub_markets:
            for m in sub_markets:
                row = {**item, **m}
                row["eventSlug"] = item_slug
                row["question"] = (
                    m.get("question") or m.get("title") or item.get("title") or item.get("question") or ""
                )
                rows.append(row)
        else:
            row = dict(item)
            row["eventSlug"] = item_slug
            row["question"] = item.get("question") or item.get("title") or ""
            rows.append(row)
    return rows


class USClient:
    def __init__(self, key_id: str, secret_key: str, rate_limiter: TokenBucketRateLimiter):
        self._rate_limiter = rate_limiter
        self._client = self._init_client(key_id, secret_key)

    def _init_client(self, key_id: str, secret_key: str):
        from polymarket_us import PolymarketUS

        client = PolymarketUS(key_id=key_id.strip(), secret_key=secret_key.strip())
        logger.info("Polymarket.US client initialized - key_id %s...", key_id.strip()[:8])
        return client

    def list_markets(self, limit: int = 200, max_pages: int = 15) -> list[dict]:
        """Storm's primary market-discovery source: the general /v1/markets
        endpoint. Colossus (a sports bot) uses events.list() -> /v1/events,
        but in production that returned 2,599/2,599 sampled markets as
        category=sports - it's a sports-specific resource, not a general
        one. Weather markets live on this broader endpoint instead."""
        all_markets: list[dict] = []
        offset = 0
        for _ in range(max_pages):
            self._rate_limiter.acquire()
            try:
                data = self._client.markets.list({"limit": limit, "active": True, "offset": offset})
            except Exception:
                logger.exception("markets.list failed at offset %d", offset)
                break

            items = _extract_items(data, "markets", "data", "results")
            if not items:
                break

            all_markets.extend(_flatten_grouped(items))
            if len(items) < limit:
                break
            offset += limit

        return all_markets

    def probe_categories(self, candidates: tuple[str, ...], limit: int = 5) -> dict[str, object]:
        """Diagnostic only: explicitly request each candidate category
        string and report how many markets came back (or the error),
        independent of the broad unfiltered listing in list_markets().
        Distinguishes "this account/key can't see Temp markets at all"
        (every candidate returns 0 or errors) from "the default query
        undercounts them for some other reason" (a candidate returns
        results)."""
        results: dict[str, object] = {}
        for candidate in candidates:
            self._rate_limiter.acquire()
            try:
                data = self._client.markets.list({"limit": limit, "active": True, "categories": [candidate]})
            except Exception as exc:
                results[candidate] = f"error: {exc}"
                continue
            items = _extract_items(data, "markets", "data", "results")
            results[candidate] = len(items)
        return results

    def retrieve_market_by_slug(self, slug: str) -> dict | None:
        """Diagnostic: fetch one specific, known-to-exist market directly
        by slug (GET /v1/market/slug/{slug}), bypassing listing/category
        filtering entirely. Decisive test for whether this key can access
        a Temp market at all - if a slug you can see/trade in the app
        comes back 404/error here, that's this key's access, not a
        listing-query quirk."""
        from polymarket_us import NotFoundError

        self._rate_limiter.acquire()
        try:
            return self._client.markets.retrieve_by_slug(slug)
        except NotFoundError as exc:
            logger.warning("retrieve_market_by_slug(%s): not found - %s", slug, exc)
            return None
        except Exception:
            logger.exception("retrieve_market_by_slug(%s) failed", slug)
            return None

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
