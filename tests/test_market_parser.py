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
        _market("Will it rain at Miami International Airport on July 20?"),
        market_slug="mia-rain-jul-20",
        yes_price=0.35,
    )
    assert spec is not None
    assert spec.variable == "rain"
    assert spec.location == "mia"
    assert spec.target_date == dt.date(2026, 7, 20)
    assert spec.market_slug == "mia-rain-jul-20"


def test_parses_temperature_above_market():
    spec = parse_weather_market(
        _market("Will the high temperature in Chicago exceed 90 degrees F?"),
        market_slug="ord-high-temp",
        yes_price=0.5,
    )
    assert spec is not None
    assert spec.variable == "temp_above"
    assert spec.threshold == 90.0
    assert spec.location == "ord"


def test_parses_temperature_below_market():
    spec = parse_weather_market(
        _market("Will the low temperature at LAX be below 50 degrees?"),
        market_slug="lax-low-temp",
        yes_price=0.5,
    )
    assert spec is not None
    assert spec.variable == "temp_below"
    assert spec.threshold == 50.0
    assert spec.location == "lax"


def test_returns_none_for_unrelated_market():
    spec = parse_weather_market(
        _market("Will the Lakers win the championship?"),
        market_slug="lakers-championship",
        yes_price=0.5,
    )
    assert spec is None


def test_returns_none_without_end_date():
    spec = parse_weather_market(
        _market("Will it snow at LAX?", end_date=""),
        market_slug="lax-snow",
        yes_price=0.5,
    )
    assert spec is None


def test_returns_none_for_untracked_city():
    # Storm only tracks MIA/ORD/LAX now - a market for a city outside that
    # set should be skipped even though it's clearly weather-related.
    spec = parse_weather_market(
        _market("Will it rain in Denver on July 20?"),
        market_slug="denver-rain-jul-20",
        yes_price=0.5,
    )
    assert spec is None
