import datetime as dt

from storm.tc_temp_parser import parse_tc_temp_slug


def test_parses_real_observed_slug_high():
    bucket = parse_tc_temp_slug("tc-temp-mdwhigh-2026-07-25-gte82lt83f")
    assert bucket is not None
    assert bucket.airport_code == "mdw"
    assert bucket.extreme == "high"
    assert bucket.target_date == dt.date(2026, 7, 25)
    assert bucket.low == 82.0
    assert bucket.high == 83.0


def test_parses_real_observed_slug_mia():
    bucket = parse_tc_temp_slug("tc-temp-miahigh-2026-07-25-gte94lt95f")
    assert bucket is not None
    assert bucket.airport_code == "mia"
    assert bucket.low == 94.0
    assert bucket.high == 95.0


def test_parses_low_variant():
    bucket = parse_tc_temp_slug("tc-temp-laxlow-2026-08-01-gte55lt56f")
    assert bucket is not None
    assert bucket.extreme == "low"
    assert bucket.airport_code == "lax"


def test_parses_negative_bounds():
    bucket = parse_tc_temp_slug("tc-temp-ordlow-2026-01-15-gte-5lt-4f")
    assert bucket is not None
    assert bucket.low == -5.0
    assert bucket.high == -4.0


def test_returns_none_for_non_matching_slug():
    assert parse_tc_temp_slug("aec-nhl-fla-car-2025-12-23") is None
    assert parse_tc_temp_slug("tc-temp-mdwhigh-2026-07-25") is None  # missing bucket suffix
    assert parse_tc_temp_slug("") is None
