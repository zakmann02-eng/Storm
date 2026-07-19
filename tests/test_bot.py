from storm.bot import StormBot


class _FakeUSClient:
    def __init__(self, markets=None, raise_error=False, probe_results=None):
        self._markets = markets if markets is not None else []
        self._raise_error = raise_error
        self._probe_results = probe_results if probe_results is not None else {}

    def list_markets(self):
        if self._raise_error:
            raise RuntimeError("SDK unavailable")
        return self._markets

    def probe_categories(self, candidates, limit=5):
        return self._probe_results


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


def _bot(us_client, gamma_client, open_meteo_client=None):
    return StormBot(
        us_client, gamma_client, _FakeWeatherClient(), _FakeTrader(), _FakeRiskManager(), min_edge=0.08,
        open_meteo_client=open_meteo_client,
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


class _SpecStub:
    lat, lon = 40.71, -74.01
    target_date = None
    location = "new york city"


def test_open_meteo_forecast_used_when_configured():
    us_client = _FakeUSClient()
    gamma_client = _FakeGammaClient()
    open_meteo_client = _FakeOpenMeteoClient(forecast={"temperature_max": 90})
    bot = _bot(us_client, gamma_client, open_meteo_client)

    assert bot._get_open_meteo_forecast(_SpecStub()) == {"temperature_max": 90}


def test_open_meteo_forecast_none_when_not_configured():
    bot = _bot(_FakeUSClient(), _FakeGammaClient(), open_meteo_client=None)

    assert bot._get_open_meteo_forecast(_SpecStub()) is None


def test_open_meteo_forecast_failure_falls_back_to_none():
    open_meteo_client = _FakeOpenMeteoClient(raise_error=True)
    bot = _bot(_FakeUSClient(), _FakeGammaClient(), open_meteo_client)

    assert bot._get_open_meteo_forecast(_SpecStub()) is None
