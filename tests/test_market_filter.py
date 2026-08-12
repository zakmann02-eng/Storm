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


def test_matches_via_category_field_even_without_keywords():
    market = {
        "question": "Chicago event #4821",
        "slug": "chicago-4821",
        "category": "Temp",
        "tags": [],
    }
    assert is_weather_market(market)


def test_matches_via_exact_tag_label_even_without_keywords():
    market = {
        "question": "Miami event #77",
        "slug": "miami-77",
        "tags": [{"label": "Temp", "slug": "temp"}],
    }
    assert is_weather_market(market)


def test_bare_temp_substring_in_question_text_does_not_false_positive():
    # "temp" as a loose substring shouldn't match unrelated words - only an
    # exact category/tag match or a real weather keyword should.
    market = {
        "question": "Will the temp worker unionization attempt succeed?",
        "slug": "temp-worker-union",
        "tags": [],
    }
    assert not is_weather_market(market)


def test_sports_category_blocks_team_name_keyword_collision():
    # Real production case: an NHL "Panthers vs Hurricanes" market matched
    # the "hurricane" weather keyword via the Carolina Hurricanes' team
    # name. An explicit non-weather category should short-circuit before
    # ever reaching the keyword fallback.
    market = {
        "question": "Who will win: FLA Panthers or CAR Hurricanes?",
        "slug": "aec-nhl-fla-car-2025-12-23",
        "description": "Who will win on the upcoming ice hockey game... FLA Panthers or CAR Hurricanes.",
        "category": "sports",
        "tags": [],
    }
    assert not is_weather_market(market)


def test_explicit_non_weather_category_short_circuits_keyword_collision():
    # Category is authoritative once present and non-weather, even when
    # question text would otherwise trip a real weather keyword.
    market = {
        "question": "Will 'Hurricane' win Best Original Song at the Oscars?",
        "slug": "hurricane-song-oscars",
        "category": "entertainment",
        "tags": [],
    }
    assert not is_weather_market(market)


def test_sports_market_type_blocks_keyword_collision_even_without_category():
    # Structured signal from Polymarket.US's real schema: sportsMarketType
    # is populated only on sports markets. Should short-circuit before
    # category/keyword checks even if category itself is missing.
    market = {
        "question": "CAR Hurricanes -1.5 puck line",
        "slug": "aec-nhl-car-puckline",
        "sportsMarketType": "SPORTS_MARKET_TYPE_SPREAD",
        "tags": [],
    }
    assert not is_weather_market(market)


def test_tag_sport_or_league_blocks_keyword_collision():
    market = {
        "question": "Miami Hurricanes to cover the spread?",
        "slug": "miami-hurricanes-spread",
        "tags": [{"label": "NCAAF", "sport": {"name": "Football"}}],
    }
    assert not is_weather_market(market)


def test_matches_real_climate_category_even_without_keywords():
    # Confirmed from a real production category breakdown (48,598 active
    # markets): Polymarket.US's actual weather category is "climate", not
    # "Temp"/"weather" - this is the exact shape that was previously
    # silently rejected on every single scan cycle.
    market = {
        "question": "Highest temperature at LAX on July 25?",
        "slug": "tc-temp-laxhigh-2026-07-25-gte89lt90f",
        "category": "climate",
        "tags": [],
    }
    assert is_weather_market(market)
