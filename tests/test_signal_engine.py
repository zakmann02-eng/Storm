import datetime as dt

from storm.market_parser import WeatherMarketSpec
from storm.signal_engine import generate_signal


def _spec(variable, threshold=None, yes_price=0.5, target_date=dt.date(2026, 7, 20)):
    return WeatherMarketSpec(
        condition_id="0xabc",
        yes_token_id="yes",
        no_token_id="no",
        question="test question",
        location="chicago",
        lat=41.8781,
        lon=-87.6298,
        variable=variable,
        threshold=threshold,
        target_date=target_date,
        yes_price=yes_price,
    )


def _period(temperature=None, is_daytime=True, pop=None, date=dt.date(2026, 7, 20)):
    period = {
        "startTime": f"{date.isoformat()}T08:00:00-05:00",
        "isDaytime": is_daytime,
    }
    if temperature is not None:
        period["temperature"] = temperature
    if pop is not None:
        period["probabilityOfPrecipitation"] = {"value": pop}
    return period


def test_rain_market_generates_yes_signal_on_high_pop():
    spec = _spec("rain", yes_price=0.2)
    periods = [_period(pop=90)]
    signal = generate_signal(spec, periods, min_edge=0.08)
    assert signal is not None
    assert signal.side == "YES"
    assert signal.estimated_probability == 0.9


def test_rain_market_generates_no_signal_on_low_pop():
    spec = _spec("rain", yes_price=0.8)
    periods = [_period(pop=5)]
    signal = generate_signal(spec, periods, min_edge=0.08)
    assert signal is not None
    assert signal.side == "NO"


def test_no_signal_when_edge_below_threshold():
    spec = _spec("rain", yes_price=0.5)
    periods = [_period(pop=52)]
    signal = generate_signal(spec, periods, min_edge=0.08)
    assert signal is None


def test_temp_above_market_favors_yes_when_forecast_well_above_threshold():
    spec = _spec("temp_above", threshold=80, yes_price=0.3)
    periods = [_period(temperature=95)]
    signal = generate_signal(spec, periods, min_edge=0.08)
    assert signal is not None
    assert signal.side == "YES"


def test_returns_none_without_matching_day_periods():
    spec = _spec("rain", target_date=dt.date(2026, 7, 21))
    periods = [_period(pop=90, date=dt.date(2026, 7, 20))]
    signal = generate_signal(spec, periods, min_edge=0.08)
    assert signal is None
