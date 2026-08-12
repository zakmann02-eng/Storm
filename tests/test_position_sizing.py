from storm.position_sizing import kelly_fraction, kelly_position_size


def test_kelly_fraction_zero_when_no_edge():
    # estimated probability equals price -> no edge -> f* == 0
    assert kelly_fraction(0.2, 0.2) == 0.0


def test_kelly_fraction_zero_when_estimate_below_price():
    assert kelly_fraction(0.1, 0.2) == 0.0


def test_kelly_fraction_positive_with_real_edge():
    # p=0.9, price=0.2 -> b=(1-0.2)/0.2=4.0 -> f*=0.9 - 0.1/4.0 = 0.875
    f = kelly_fraction(0.9, 0.2)
    assert abs(f - 0.875) < 1e-9


def test_kelly_fraction_clamped_to_unit_interval():
    f = kelly_fraction(0.999, 0.01)
    assert 0.0 <= f <= 1.0


def test_kelly_fraction_handles_unusable_price():
    assert kelly_fraction(0.5, 0.0) == 0.0
    assert kelly_fraction(0.5, 1.0) == 0.0


def test_kelly_position_size_scales_with_bankroll():
    small = kelly_position_size(0.9, 0.2, bankroll=10.0, kelly_multiplier=0.5)
    big = kelly_position_size(0.9, 0.2, bankroll=100.0, kelly_multiplier=0.5)
    assert big == small * 10


def test_kelly_position_size_applies_multiplier():
    full = kelly_position_size(0.9, 0.2, bankroll=100.0, kelly_multiplier=1.0)
    half = kelly_position_size(0.9, 0.2, bankroll=100.0, kelly_multiplier=0.5)
    assert abs(half - full / 2) < 1e-9


def test_kelly_position_size_zero_bankroll():
    assert kelly_position_size(0.9, 0.2, bankroll=0.0) == 0.0
    assert kelly_position_size(0.9, 0.2, bankroll=-5.0) == 0.0
