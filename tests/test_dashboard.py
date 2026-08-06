from fastapi.testclient import TestClient

from storm.dashboard import build_app
from storm.dashboard_state import DashboardState


def test_index_serves_html():
    client = TestClient(build_app(DashboardState()))
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "Storm Weather Dashboard" in res.text


def test_healthz():
    client = TestClient(build_app(DashboardState()))
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_api_state_reflects_dashboard_state():
    state = DashboardState()
    state.update_weather("mia", {"blended_forecast": 91.5})
    state.update_market("mia", "tc-temp-miahigh-2026-07-25-gte91lt92f", {"side": "YES", "edge": 0.15})
    state.record_history({"airport": "mia", "market_slug": "tc-temp-miahigh-2026-07-25-gte91lt92f", "side": "YES"})
    state.record_scan_summary(total_markets=25089, weather_related=6)

    client = TestClient(build_app(state))
    res = client.get("/api/state")
    assert res.status_code == 200
    body = res.json()

    assert body["weather"]["mia"]["blended_forecast"] == 91.5
    assert body["markets"]["mia"]["tc-temp-miahigh-2026-07-25-gte91lt92f"]["side"] == "YES"
    assert len(body["history"]) == 1
    assert body["last_scan_summary"] == {"total_markets": 25089, "weather_related": 6}


def test_api_state_includes_all_three_tracked_airports():
    client = TestClient(build_app(DashboardState()))
    body = client.get("/api/state").json()

    assert set(body["airports"].keys()) == {"mia", "ord", "lax"}
    assert body["airports"]["ord"]["name"] == "Chicago O'Hare International Airport"


def test_api_state_empty_before_any_scan():
    client = TestClient(build_app(DashboardState()))
    body = client.get("/api/state").json()

    assert body["last_scan_at"] is None
    assert body["weather"] == {}
    assert body["markets"] == {}
    assert body["history"] == []
