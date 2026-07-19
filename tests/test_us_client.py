from storm.us_client import _extract_events, _flatten_events


def test_extract_events_from_bare_list():
    assert _extract_events([{"id": 1}]) == [{"id": 1}]


def test_extract_events_from_wrapped_dict():
    assert _extract_events({"data": [{"id": 1}]}) == [{"id": 1}]
    assert _extract_events({"events": [{"id": 2}]}) == [{"id": 2}]
    assert _extract_events({"results": [{"id": 3}]}) == [{"id": 3}]


def test_extract_events_handles_empty_or_unknown_shape():
    assert _extract_events(None) == []
    assert _extract_events({}) == []
    assert _extract_events("nope") == []


def test_flatten_events_expands_grouped_range_buckets():
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
    rows = _flatten_events([event])
    assert len(rows) == 2
    assert rows[0]["question"] == "78 or below"
    assert rows[0]["category"] == "Temp"
    assert rows[0]["eventSlug"] == "nyc-high-temp-jul-18"
    assert rows[1]["conditionId"] == "0x2"


def test_flatten_events_handles_ungrouped_event():
    event = {"slug": "will-it-rain-nyc", "title": "Will it rain in NYC on July 20?"}
    rows = _flatten_events([event])
    assert len(rows) == 1
    assert rows[0]["question"] == "Will it rain in NYC on July 20?"
    assert rows[0]["eventSlug"] == "will-it-rain-nyc"
