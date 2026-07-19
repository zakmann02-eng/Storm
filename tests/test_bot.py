from storm.bot import StormBot


class _FakeUSClient:
    def __init__(self, markets=None, raise_error=False):
        self._markets = markets if markets is not None else []
        self._raise_error = raise_error

    def list_events(self):
        if self._raise_error:
            raise RuntimeError("SDK unavailable")
        return self._markets


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


def _bot(us_client, gamma_client):
    return StormBot(us_client, gamma_client, _FakeWeatherClient(), _FakeTrader(), _FakeRiskManager(), min_edge=0.08)


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
