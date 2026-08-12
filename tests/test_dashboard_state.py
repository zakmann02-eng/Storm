import threading

from storm.dashboard_state import DashboardState


def test_update_and_snapshot_weather():
    state = DashboardState()
    state.update_weather("mia", {"temperature_max": 90})

    snap = state.snapshot()
    assert snap["weather"]["mia"]["temperature_max"] == 90
    assert "updated_at" in snap["weather"]["mia"]


def test_update_and_snapshot_market():
    state = DashboardState()
    state.update_market("lax", "tc-temp-laxhigh-2026-07-25-gte82lt83f", {"side": "YES", "edge": 0.12})

    snap = state.snapshot()
    entry = snap["markets"]["lax"]["tc-temp-laxhigh-2026-07-25-gte82lt83f"]
    assert entry["side"] == "YES"
    assert entry["edge"] == 0.12


def test_record_history_appends_newest_first():
    state = DashboardState()
    state.record_history({"market_slug": "a"})
    state.record_history({"market_slug": "b"})

    snap = state.snapshot()
    assert [h["market_slug"] for h in snap["history"]] == ["b", "a"]


def test_history_respects_limit():
    state = DashboardState(history_limit=3)
    for i in range(5):
        state.record_history({"i": i})

    snap = state.snapshot()
    assert len(snap["history"]) == 3
    assert [h["i"] for h in snap["history"]] == [4, 3, 2]


def test_record_scan_summary():
    state = DashboardState()
    state.record_scan_summary(total_markets=25089, weather_related=6)

    snap = state.snapshot()
    assert snap["last_scan_summary"] == {"total_markets": 25089, "weather_related": 6}
    assert snap["last_scan_at"] is not None


def test_snapshot_is_a_copy_not_a_live_reference():
    state = DashboardState()
    state.update_weather("ord", {"temperature_max": 70})

    snap = state.snapshot()
    snap["weather"]["ord"]["temperature_max"] = 999  # mutate the copy

    fresh = state.snapshot()
    assert fresh["weather"]["ord"]["temperature_max"] == 70  # internal state untouched


def test_concurrent_updates_do_not_crash_or_lose_data():
    state = DashboardState()

    def writer(n):
        for i in range(50):
            state.update_market("mia", f"slug-{n}-{i}", {"i": i})

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    snap = state.snapshot()
    assert len(snap["markets"]["mia"]) == 200  # 4 threads * 50 unique slugs each
