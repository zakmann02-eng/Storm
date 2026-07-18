from storm.market_filter import is_weather_market


def test_matches_obvious_weather_market():
    market = {"question": "Will it rain in New York City on July 20?", "slug": "nyc-rain-jul-20", "tags": []}
    assert is_weather_market(market)


def test_matches_temperature_market_via_tags():
    market = {
        "question": "Highest temp in Chicago?",
        "slug": "chicago-temp",
        "tags": [{"label": "Weather", "slug": "weather"}],
    }
    assert is_weather_market(market)


def test_ignores_unrelated_sports_market():
    market = {
        "question": "Will the Lakers win the NBA championship?",
        "slug": "lakers-championship",
        "tags": [{"label": "NBA", "slug": "nba"}],
    }
    assert not is_weather_market(market)


def test_excludes_false_positive_storm_phrase():
    market = {"question": "Will there be a political storm over the bill?", "slug": "political-storm", "tags": []}
    assert not is_weather_market(market)
