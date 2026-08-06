from storm.airports import AIRPORTS, find_airport_by_alias


def test_exactly_three_airports_tracked():
    assert set(AIRPORTS.keys()) == {"mia", "ord", "lax"}


def test_finds_by_exact_code():
    assert find_airport_by_alias("mia").code == "mia"
    assert find_airport_by_alias("lax").code == "lax"


def test_finds_by_full_name():
    assert find_airport_by_alias("weather at los angeles international airport").code == "lax"


def test_finds_ord_via_ohare_alias():
    assert find_airport_by_alias("conditions at o'hare today").code == "ord"


def test_returns_none_for_untracked_city():
    assert find_airport_by_alias("weather in denver today") is None
