import pytest

from storm.bucket_signal import (
    BucketSignal,
    TemperatureBucket,
    bucket_probability,
    evaluate_bucket,
    generate_bucket_signals,
)


def test_bucket_probability_open_below():
    # P(temp <= 78) with mean=80, stdev=3 should be well under 50%
    p = bucket_probability(mean=80, stdev=3, low=None, high=78)
    assert 0.0 < p < 0.5


def test_bucket_probability_open_above():
    p = bucket_probability(mean=80, stdev=3, low=87, high=None)
    assert 0.0 < p < 0.2


def test_bucket_probability_bounded_range():
    p = bucket_probability(mean=80, stdev=3, low=79, high=81)
    assert 0.0 < p < 1.0


def test_bucket_probability_centered_bucket_has_highest_mass():
    # Buckets straddling the forecast mean should carry more probability
    # mass than buckets far from it.
    near = bucket_probability(mean=80, stdev=3, low=79, high=81)
    far = bucket_probability(mean=80, stdev=3, low=95, high=97)
    assert near > far


def test_bucket_probabilities_sum_to_one_across_a_complete_partition():
    mean, stdev = 80.0, 3.0
    buckets = [
        (None, 78),
        (78, 79),
        (79, 80),
        (80, 81),
        (81, 82),
        (82, None),
    ]
    total = sum(bucket_probability(mean, stdev, low, high) for low, high in buckets)
    assert abs(total - 1.0) < 1e-9


def test_bucket_probability_rejects_non_positive_stdev():
    with pytest.raises(ValueError):
        bucket_probability(mean=80, stdev=0, low=79, high=81)


def test_bucket_probability_rejects_inverted_range():
    with pytest.raises(ValueError):
        bucket_probability(mean=80, stdev=3, low=81, high=79)


def _bucket(low, high, yes_price, slug="nyc-79-80"):
    return TemperatureBucket(market_slug=slug, condition_id=f"0x{slug}", low=low, high=high, yes_price=yes_price)


def test_generate_bucket_signals_fires_yes_on_underpriced_bucket():
    # Forecast centered right on this bucket, but market prices it cheap.
    buckets = [_bucket(79, 81, yes_price=0.10)]
    signals = generate_bucket_signals(buckets, forecast_mean=80, forecast_stdev=3, min_edge=0.08)
    assert len(signals) == 1
    assert signals[0].side == "YES"
    assert isinstance(signals[0], BucketSignal)


def test_generate_bucket_signals_fires_no_on_overpriced_bucket():
    # A far-away bucket the market still prices high.
    buckets = [_bucket(95, 97, yes_price=0.90)]
    signals = generate_bucket_signals(buckets, forecast_mean=80, forecast_stdev=3, min_edge=0.08)
    assert len(signals) == 1
    assert signals[0].side == "NO"


def test_generate_bucket_signals_skips_fairly_priced_bucket():
    buckets = [_bucket(79, 81, yes_price=0.50)]
    signals = generate_bucket_signals(buckets, forecast_mean=80, forecast_stdev=3, min_edge=0.30)
    # edge would need to be huge to clear a 30% threshold on a near-fair bucket
    assert signals == []


def test_evaluate_bucket_returns_signal_on_underpriced_bucket():
    bucket = _bucket(79, 81, yes_price=0.10)
    signal = evaluate_bucket(bucket, forecast_mean=80, forecast_stdev=3, min_edge=0.08)
    assert signal is not None
    assert signal.side == "YES"


def test_evaluate_bucket_returns_none_on_fair_price():
    bucket = _bucket(79, 81, yes_price=0.50)
    signal = evaluate_bucket(bucket, forecast_mean=80, forecast_stdev=3, min_edge=0.30)
    assert signal is None


def test_generate_bucket_signals_evaluates_each_bucket_independently():
    buckets = [
        _bucket(None, 78, yes_price=0.99, slug="a"),
        _bucket(79, 81, yes_price=0.03, slug="b"),
        _bucket(95, None, yes_price=0.50, slug="c"),
    ]
    signals = generate_bucket_signals(buckets, forecast_mean=80, forecast_stdev=3, min_edge=0.08)
    slugs = {s.bucket.market_slug for s in signals}
    # bucket "b" is badly underpriced given the forecast is centered there
    assert "b" in slugs
