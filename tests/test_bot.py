import datetime as dt

from storm.airports import AIRPORTS
from storm.bot import StormBot


class _FakeUSClient:
    def __init__(self, markets=None, raise_error=False, probe_results=None, slug_probe_result="__unset__"):
        self._markets = markets if markets is not None else []
        self._raise_error = raise_error
        self._probe_results = probe_results if probe_results is not None else {}
        self._slug_probe_result = slug_probe_result

    def list_markets(self):
        if self._raise_error:
            raise RuntimeError("SDK unavailable")
        return self._markets

    def probe_categories(self, candidates, limit=5):
        return self._probe_results

    def retrieve_market_by_slug(self, slug):
        if self._slug_probe_result == "__unset__":
            return None
        return self._slug_probe_result


class _FakeGammaClient:
    def __init__(self, markets=None):
        self._markets = markets or []

    def iter_active_markets(self):
        return iter(self._markets)


class _FakeWeatherClient:
    def get_forecast_for_date(self, lat, lon, target_date):
        return []


class _FakeTrader:
    def __init__(self):
        self.executed = []

    def execute(self, signal):
        self.executed.append(signal)


class _FakeRiskManager:
    def already_traded(self, condition_id):
        return False


class _FakeOpenMeteoClient:
    def __init__(self, forecast=None, raise_error=False):
        self._forecast = forecast
        self._raise_error = raise_error

    def get_forecast_for_date(self, lat, lon, target_date):
        if self._raise_error:
            raise RuntimeError("open-meteo unavailable")
        return self._forecast


def _bot(us_client, gamma_client, open_meteo_client=None, diagnostic_probe_slug=""):
    return StormBot(
        us_client, gamma_client, _FakeWeatherClient(), _FakeTrader(), _FakeRiskManager(), min_edge=0.08,
        open_meteo_client=open_meteo_client,
        diagnostic_probe_slug=diagnostic_probe_slug,
    )


def test_uses_sdk_markets_when_available():
    us_client = _FakeUSClient(markets=[{"slug": "a"}, {"slug": "b"}])
    gamma_client = _FakeGammaClient(markets=[{"slug": "should-not-be-used"}])
    bot = _bot(us_client, gamma_client)

    markets = bot._discover_markets()
    assert markets == [{"slug": "a"}, {"slug": "b"}]


def test_falls_back_to_gamma_when_sdk_returns_nothing():
    us_client = _FakeUSClient(markets=[])
    gamma_client = _FakeGammaClient(markets=[{"slug": "fallback"}])
    bot = _bot(us_client, gamma_client)

    markets = bot._discover_markets()
    assert markets == [{"slug": "fallback"}]


def test_falls_back_to_gamma_when_sdk_raises():
    us_client = _FakeUSClient(raise_error=True)
    gamma_client = _FakeGammaClient(markets=[{"slug": "fallback"}])
    bot = _bot(us_client, gamma_client)

    markets = bot._discover_markets()
    assert markets == [{"slug": "fallback"}]


def test_run_cycle_skips_when_paused(monkeypatch):
    monkeypatch.setenv("PAUSED", "true")
    us_client = _FakeUSClient(markets=[{"slug": "a", "question": "Highest temp in NYC?"}])
    gamma_client = _FakeGammaClient()
    bot = _bot(us_client, gamma_client)

    bot.run_cycle()  # should not raise, and should not process anything


def test_discovery_diagnostics_only_logs_once(caplog):
    import logging

    markets = [
        {"slug": "a", "question": "Highest temperature in NYC?", "category": "temp"},
        {"slug": "b", "question": "Lakers vs Celtics", "category": "sports"},
    ]
    us_client = _FakeUSClient(markets=markets)
    gamma_client = _FakeGammaClient()
    bot = _bot(us_client, gamma_client)

    with caplog.at_level(logging.INFO, logger="storm.bot"):
        bot._log_discovery_diagnostics(markets)
        first_pass_count = len(caplog.records)
        bot._log_discovery_diagnostics(markets)
        assert len(caplog.records) == first_pass_count  # no new logs on second call


def test_discovery_diagnostics_finds_loose_text_candidates(caplog):
    import logging

    markets = [{"slug": "nyc-temp", "question": "Highest temperature in NYC?", "category": "temp"}]
    us_client = _FakeUSClient(markets=markets)
    gamma_client = _FakeGammaClient()
    bot = _bot(us_client, gamma_client)

    with caplog.at_level(logging.INFO, logger="storm.bot"):
        bot._log_discovery_diagnostics(markets)

    assert any("loose-text" in r.message for r in caplog.records)


def test_discovery_diagnostics_includes_category_probe_results(caplog):
    import logging

    markets = [{"slug": "a", "question": "Lakers vs Celtics", "category": "sports"}]
    us_client = _FakeUSClient(markets=markets, probe_results={"Temp": 0, "temp": 3})
    gamma_client = _FakeGammaClient()
    bot = _bot(us_client, gamma_client)

    with caplog.at_level(logging.INFO, logger="storm.bot"):
        bot._log_discovery_diagnostics(markets)

    assert any("category probe" in r.message and "temp" in r.message for r in caplog.records)


def test_slug_probe_not_run_when_unconfigured(caplog):
    import logging

    us_client = _FakeUSClient(markets=[])
    bot = _bot(us_client, _FakeGammaClient(), diagnostic_probe_slug="")

    with caplog.at_level(logging.INFO, logger="storm.bot"):
        bot._log_discovery_diagnostics([])

    assert not any("slug probe" in r.message for r in caplog.records)


def test_slug_probe_logs_found_market(caplog):
    import logging

    us_client = _FakeUSClient(markets=[], slug_probe_result={"id": "123", "question": "Highest temp in NYC?"})
    bot = _bot(us_client, _FakeGammaClient(), diagnostic_probe_slug="highest-temp-nyc")

    with caplog.at_level(logging.INFO, logger="storm.bot"):
        bot._log_discovery_diagnostics([])

    messages = [r.message for r in caplog.records]
    assert any("slug probe" in m and "FOUND" in m for m in messages)


def test_slug_probe_logs_not_found(caplog):
    import logging

    us_client = _FakeUSClient(markets=[], slug_probe_result=None)
    bot = _bot(us_client, _FakeGammaClient(), diagnostic_probe_slug="highest-temp-nyc")

    with caplog.at_level(logging.INFO, logger="storm.bot"):
        bot._log_discovery_diagnostics([])

    messages = [r.message for r in caplog.records]
    assert any("slug probe" in m and "NOT FOUND" in m for m in messages)


_MIA = AIRPORTS["mia"]
_TARGET_DATE = dt.date(2026, 7, 25)


def test_open_meteo_forecast_used_when_configured():
    us_client = _FakeUSClient()
    gamma_client = _FakeGammaClient()
    open_meteo_client = _FakeOpenMeteoClient(forecast={"temperature_max": 90})
    bot = _bot(us_client, gamma_client, open_meteo_client)

    assert bot._fetch_open_meteo(_MIA, _TARGET_DATE) == {"temperature_max": 90}


def test_open_meteo_forecast_none_when_not_configured():
    bot = _bot(_FakeUSClient(), _FakeGammaClient(), open_meteo_client=None)

    assert bot._fetch_open_meteo(_MIA, _TARGET_DATE) is None


def test_open_meteo_forecast_failure_falls_back_to_none():
    open_meteo_client = _FakeOpenMeteoClient(raise_error=True)
    bot = _bot(_FakeUSClient(), _FakeGammaClient(), open_meteo_client)

    assert bot._fetch_open_meteo(_MIA, _TARGET_DATE) is None


# --- Integration: _process_market routing, trading, and dashboard recording ---


class _ConfigurableWeatherClient:
    def __init__(self, periods=None):
        self._periods = periods if periods is not None else []

    def get_forecast_for_date(self, lat, lon, target_date):
        return self._periods


def _nws_periods(target_date, high_temp):
    return [
        {"startTime": f"{target_date.isoformat()}T08:00:00-05:00", "isDaytime": True, "temperature": high_temp},
        {"startTime": f"{target_date.isoformat()}T20:00:00-05:00", "isDaytime": False, "temperature": high_temp - 15},
    ]


def _tc_temp_market(slug, yes_price):
    return {
        "id": f"0x{slug}",
        "slug": slug,
        "marketSides": [{"long": True, "price": yes_price}, {"long": False, "price": 1 - yes_price}],
    }


def test_process_market_tc_temp_underpriced_bucket_trades_and_records_dashboard():
    from storm.dashboard_state import DashboardState

    # bucket [89, 90) at mean=89, stdev=3 carries ~13% estimated probability
    # (bucket_signal.py's normal model); pricing it at 2c is clearly cheap.
    slug = "tc-temp-miahigh-2026-07-25-gte89lt90f"
    market = _tc_temp_market(slug, yes_price=0.02)
    weather_client = _ConfigurableWeatherClient(_nws_periods(dt.date(2026, 7, 25), high_temp=89))
    trader = _FakeTrader()
    dashboard = DashboardState()

    bot = StormBot(
        _FakeUSClient(), _FakeGammaClient(), weather_client, trader, _FakeRiskManager(), min_edge=0.08,
        dashboard_state=dashboard,
    )
    bot._process_market(market)

    assert len(trader.executed) == 1
    assert trader.executed[0].side == "YES"

    snap = dashboard.snapshot()
    assert "mia" in snap["weather"]
    entry = snap["markets"]["mia"][slug]
    assert entry["type"] == "tc-temp"
    assert entry["side"] == "YES"
    assert len(snap["history"]) == 1
    assert snap["history"][0]["market_slug"] == slug


def test_process_market_tc_temp_fair_price_records_dashboard_without_trading():
    from storm.dashboard_state import DashboardState

    # bucket [89, 90) at mean=89, stdev=3 carries ~13% estimated probability;
    # pricing it right there leaves no edge on either side.
    slug = "tc-temp-laxhigh-2026-07-25-gte89lt90f"
    market = _tc_temp_market(slug, yes_price=0.13)
    weather_client = _ConfigurableWeatherClient(_nws_periods(dt.date(2026, 7, 25), high_temp=89))
    trader = _FakeTrader()
    dashboard = DashboardState()

    bot = StormBot(
        _FakeUSClient(), _FakeGammaClient(), weather_client, trader, _FakeRiskManager(), min_edge=0.08,
        dashboard_state=dashboard,
    )
    bot._process_market(market)

    assert trader.executed == []
    snap = dashboard.snapshot()
    assert snap["markets"]["lax"][slug]["side"] is None
    assert snap["history"] == []


def test_process_market_tc_temp_untracked_airport_is_ignored():
    # mdw (Midway) is real production data but not one of Storm's three
    # tracked airports (ord was chosen instead) - should be skipped entirely.
    from storm.dashboard_state import DashboardState

    slug = "tc-temp-mdwhigh-2026-07-25-gte89lt90f"
    market = _tc_temp_market(slug, yes_price=0.10)
    trader = _FakeTrader()
    dashboard = DashboardState()

    bot = StormBot(
        _FakeUSClient(), _FakeGammaClient(), _FakeWeatherClient(), trader, _FakeRiskManager(), min_edge=0.08,
        dashboard_state=dashboard,
    )
    bot._process_market(market)

    assert trader.executed == []
    assert dashboard.snapshot()["markets"] == {}


def test_process_market_tc_temp_no_forecast_yet_is_skipped():
    from storm.dashboard_state import DashboardState

    slug = "tc-temp-miahigh-2026-07-25-gte89lt90f"
    market = _tc_temp_market(slug, yes_price=0.10)
    trader = _FakeTrader()
    dashboard = DashboardState()

    bot = StormBot(
        _FakeUSClient(), _FakeGammaClient(), _FakeWeatherClient(), trader, _FakeRiskManager(), min_edge=0.08,
        dashboard_state=dashboard,
    )
    bot._process_market(market)  # _FakeWeatherClient returns [] -> no NWS, no Open-Meteo configured

    assert trader.executed == []
    assert dashboard.snapshot()["weather"] == {}
    assert dashboard.snapshot()["markets"] == {}


def test_process_market_threshold_market_trades_and_records_dashboard():
    from storm.dashboard_state import DashboardState

    market = {
        "id": "0xrain-mia",
        "slug": "mia-rain-jul-25",
        "question": "Will it rain at Miami International Airport on July 25?",
        "endDate": "2026-07-25T00:00:00Z",
        "marketSides": [{"long": True, "price": 0.10}, {"long": False, "price": 0.90}],
    }
    weather_client = _ConfigurableWeatherClient([
        {
            "startTime": "2026-07-25T08:00:00-05:00",
            "isDaytime": True,
            "probabilityOfPrecipitation": {"value": 90},
        }
    ])
    trader = _FakeTrader()
    dashboard = DashboardState()

    bot = StormBot(
        _FakeUSClient(), _FakeGammaClient(), weather_client, trader, _FakeRiskManager(), min_edge=0.08,
        dashboard_state=dashboard,
    )
    bot._process_market(market)

    assert len(trader.executed) == 1
    assert trader.executed[0].side == "YES"

    snap = dashboard.snapshot()
    entry = snap["markets"]["mia"]["mia-rain-jul-25"]
    assert entry["type"] == "rain"
    assert entry["side"] == "YES"
    assert len(snap["history"]) == 1


def test_process_market_threshold_market_untracked_city_skips_dashboard():
    from storm.dashboard_state import DashboardState

    market = {
        "id": "0xrain-denver",
        "slug": "denver-rain-jul-25",
        "question": "Will it rain in Denver on July 25?",
        "endDate": "2026-07-25T00:00:00Z",
        "marketSides": [{"long": True, "price": 0.10}, {"long": False, "price": 0.90}],
    }
    weather_client = _ConfigurableWeatherClient([
        {
            "startTime": "2026-07-25T08:00:00-05:00",
            "isDaytime": True,
            "probabilityOfPrecipitation": {"value": 90},
        }
    ])
    trader = _FakeTrader()
    dashboard = DashboardState()

    bot = StormBot(
        _FakeUSClient(), _FakeGammaClient(), weather_client, trader, _FakeRiskManager(), min_edge=0.08,
        dashboard_state=dashboard,
    )
    bot._process_market(market)

    # Denver isn't parseable at all (find_airport_by_alias returns None for
    # spec-building), so parse_weather_market itself returns None upstream.
    assert trader.executed == []
    assert dashboard.snapshot()["markets"] == {}


def test_process_market_without_dashboard_state_does_not_crash():
    slug = "tc-temp-miahigh-2026-07-25-gte89lt90f"
    market = _tc_temp_market(slug, yes_price=0.02)
    weather_client = _ConfigurableWeatherClient(_nws_periods(dt.date(2026, 7, 25), high_temp=89))
    trader = _FakeTrader()

    bot = StormBot(
        _FakeUSClient(), _FakeGammaClient(), weather_client, trader, _FakeRiskManager(), min_edge=0.08,
    )
    bot._process_market(market)  # no dashboard_state configured - must be a safe no-op

    assert len(trader.executed) == 1


def test_run_cycle_records_scan_summary_to_dashboard():
    from storm.dashboard_state import DashboardState

    markets = [{"slug": "a", "question": "Highest temperature in NYC?"}]
    us_client = _FakeUSClient(markets=markets)
    dashboard = DashboardState()

    bot = StormBot(
        us_client, _FakeGammaClient(), _FakeWeatherClient(), _FakeTrader(), _FakeRiskManager(), min_edge=0.08,
        dashboard_state=dashboard,
    )
    bot.run_cycle()

    snap = dashboard.snapshot()
    assert snap["last_scan_summary"] == {"total_markets": 1, "weather_related": 1}
    assert snap["last_scan_at"] is not None
