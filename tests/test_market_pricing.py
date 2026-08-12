from storm.market_pricing import parse_yes_no_prices


def _side(long_side, price=None, quote_value=None):
    side = {"long": long_side}
    if price is not None:
        side["price"] = price
    if quote_value is not None:
        side["quote"] = {"value": quote_value, "currency": "USD"}
    return side


def test_prefers_market_sides_when_present():
    market = {
        "marketSides": [_side(True, price="0.35"), _side(False, price="0.65")],
        "outcomePrices": '["0.99", "0.01"]',  # should be ignored - marketSides wins
    }
    assert parse_yes_no_prices(market) == [0.35, 0.65]


def test_market_sides_reads_price_from_quote_when_price_field_missing():
    market = {"marketSides": [_side(True, quote_value="0.40"), _side(False, quote_value="0.60")]}
    assert parse_yes_no_prices(market) == [0.40, 0.60]


def test_market_sides_derives_no_price_when_only_long_side_present():
    market = {"marketSides": [_side(True, price="0.30")]}
    assert parse_yes_no_prices(market) == [0.30, 0.70]


def test_falls_back_to_legacy_outcome_prices_when_no_market_sides():
    market = {"outcomePrices": '["0.55", "0.45"]'}
    assert parse_yes_no_prices(market) == [0.55, 0.45]


def test_falls_back_to_legacy_when_market_sides_empty():
    market = {"marketSides": [], "outcomePrices": '["0.20", "0.80"]'}
    assert parse_yes_no_prices(market) == [0.20, 0.80]


def test_falls_back_to_legacy_when_market_sides_have_no_usable_price():
    market = {"marketSides": [{"long": True}, {"long": False}], "outcomePrices": '["0.10", "0.90"]'}
    assert parse_yes_no_prices(market) == [0.10, 0.90]


def test_returns_empty_list_when_nothing_usable():
    assert parse_yes_no_prices({}) == []
