from storm.us_client import USClient, _extract_items, _flatten_grouped


def test_extract_items_from_bare_list():
    assert _extract_items([{"id": 1}], "markets") == [{"id": 1}]


def test_extract_items_from_wrapped_dict():
    assert _extract_items({"markets": [{"id": 1}]}, "markets", "data") == [{"id": 1}]
    assert _extract_items({"data": [{"id": 2}]}, "markets", "data") == [{"id": 2}]
    assert _extract_items({"results": [{"id": 3}]}, "results") == [{"id": 3}]


def test_extract_items_handles_empty_or_unknown_shape():
    assert _extract_items(None, "markets") == []
    assert _extract_items({}, "markets") == []
    assert _extract_items("nope", "markets") == []


def test_flatten_grouped_expands_nested_range_buckets():
    event = {
        "slug": "nyc-high-temp-jul-18",
        "title": "Highest temperature in NYC on July 18?",
        "category": "Temp",
        "tags": [{"label": "Temp", "slug": "temp"}],
        "endDate": "2026-07-18T00:00:00Z",
        "markets": [
            {"conditionId": "0x1", "question": "78 or below", "outcomePrices": ["0.99", "0.01"]},
            {"conditionId": "0x2", "question": "79 to 80", "outcomePrices": ["0.03", "0.97"]},
        ],
    }
    rows = _flatten_grouped([event])
    assert len(rows) == 2
    assert rows[0]["question"] == "78 or below"
    assert rows[0]["category"] == "Temp"
    assert rows[0]["eventSlug"] == "nyc-high-temp-jul-18"
    assert rows[1]["conditionId"] == "0x2"


def test_flatten_grouped_handles_already_flat_market():
    # polymarket-us's /v1/markets returns individual markets directly
    # (MarketDetail has "title", not "question", and no nested "markets").
    market = {"slug": "will-it-rain-nyc", "title": "Will it rain in NYC on July 20?", "eventSlug": "rain-nyc-event"}
    rows = _flatten_grouped([market])
    assert len(rows) == 1
    assert rows[0]["question"] == "Will it rain in NYC on July 20?"
    assert rows[0]["eventSlug"] == "rain-nyc-event"


# --- list_markets pagination: retry-then-skip on page failure ---


class _FakeRateLimiter:
    def acquire(self):
        pass


class _FakeEvents:
    """responses[i] is either a dict (returned as-is) or an Exception
    (raised) for the i-th call to .list(), in order. Extra calls past the
    end reuse the last response."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def list(self, params):
        self.calls.append(params)
        i = min(len(self.calls) - 1, len(self._responses) - 1)
        response = self._responses[i]
        if isinstance(response, Exception):
            raise response
        return response


def _us_client(responses):
    client = USClient.__new__(USClient)
    client._rate_limiter = _FakeRateLimiter()
    client._client = type("FakeSDK", (), {"events": _FakeEvents(responses)})()
    return client


def test_list_markets_paginates_until_genuinely_empty_page():
    client = _us_client([
        {"events": [{"slug": "a"}]},
        {"events": [{"slug": "b"}]},
        {"events": []},
    ])
    markets = client.list_markets(limit=1)
    assert [m["slug"] for m in markets] == ["a", "b"]
    assert client._client.events.calls[0]["offset"] == 0
    assert client._client.events.calls[1]["offset"] == 1
    assert client._client.events.calls[2]["offset"] == 2


def test_list_markets_retries_a_failed_page_then_succeeds(monkeypatch):
    monkeypatch.setattr("storm.us_client.time.sleep", lambda _: None)
    client = _us_client([
        RuntimeError("504"),
        {"events": [{"slug": "a"}]},  # succeeds on retry
        {"events": []},
    ])
    markets = client.list_markets(limit=1, max_retries_per_page=2)
    assert [m["slug"] for m in markets] == ["a"]


def test_list_markets_skips_a_persistently_failing_page_and_keeps_going(monkeypatch):
    # Real production case: offset X fails every single attempt (a
    # persistent 504), but markets past it should still be discovered
    # rather than the whole scan silently stopping there.
    monkeypatch.setattr("storm.us_client.time.sleep", lambda _: None)
    client = _us_client([
        {"events": [{"slug": "a"}]},
        RuntimeError("504"),
        RuntimeError("504"),
        RuntimeError("504"),
        {"events": [{"slug": "b"}]},
        {"events": []},
    ])
    markets = client.list_markets(limit=1, max_retries_per_page=2)
    assert [m["slug"] for m in markets] == ["a", "b"]
