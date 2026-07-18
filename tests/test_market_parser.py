import datetime as dt

from storm.market_parser import parse_weather_market


def _market(question, end_date="2026-07-20T00:00:00Z", description=""):
    return {
        "question": question,
        "description": description,
        "conditionId": "0xabc",
        "endDate": end_date,
    }


def test_parses_rain_market():
    spec = parse_weather_market(
        _market("Will it rain in New York City on July 20?"),
        yes_token_id="yes-1",
        no_token_id="no-1",
        yes_price=0.35,
    )
    assert spec is not None
    assert spec.variable == "rain"
    assert spec.location == "new york city"
    assert spec.target_date == dt.date(2026, 7, 20)
    assert spec.yes_token_id == "yes-1"


def test_parses_temperature_above_market():
    spec = parse_weather_market(
        _market("Will the high temperature in Chicago exceed 90 degrees F?"),
        yes_token_id="yes-2",
        no_token_id="no-2",
        yes_price=0.5,
    )
    assert spec is not None
    assert spec.variable == "temp_above"
    assert spec.threshold == 90.0
    assert spec.location == "chicago"


def test_parses_temperature_below_market():
    spec = parse_weather_market(
        _market("Will the low temperature in Denver be below 20 degrees?"),
        yes_token_id="yes-3",
        no_token_id="no-3",
        yes_price=0.5,
    )
    assert spec is not None
    assert spec.variable == "temp_below"
    assert spec.threshold == 20.0


def test_returns_none_for_unrelated_market():
    spec = parse_weather_market(
        _market("Will the Lakers win the championship?"),
        yes_token_id="yes-4",
        no_token_id="no-4",
        yes_price=0.5,
    )
    assert spec is None


def test_returns_none_without_end_date():
    spec = parse_weather_market(
        _market("Will it snow in Boston?", end_date=""),
        yes_token_id="yes-5",
        no_token_id="no-5",
        yes_price=0.5,
    )
    assert spec is None
