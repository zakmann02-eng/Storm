from storm.risk_manager import RiskManager


def _rm(tmp_path, **overrides):
    defaults = dict(
        min_trade_usd=0.10,
        max_trade_usd=1.00,
        max_trades_session=10,
        max_daily_spend_usdc=5.00,
        state_file=tmp_path / "state.json",
    )
    defaults.update(overrides)
    return RiskManager(**defaults)


def _trade(side="YES", price=0.5, usdc=0.5):
    return {"side": side, "question": "q", "price": price, "usdc": usdc}


def test_caps_to_max_trade_usd(tmp_path):
    rm = _rm(tmp_path, max_trade_usd=0.50)
    assert rm.size_order(5.0) == 0.50


def test_skips_below_min_trade_floor(tmp_path):
    rm = _rm(tmp_path, min_trade_usd=0.20, max_daily_spend_usdc=0.15)
    assert rm.size_order(1.0) == 0


def test_caps_to_remaining_daily_budget(tmp_path):
    rm = _rm(tmp_path, max_trade_usd=100, max_daily_spend_usdc=1.5)
    assert rm.size_order(5.0) == 1.5
    rm.record_trade("cond-1", 1.5, _trade(usdc=1.5))
    assert rm.size_order(5.0) == 0


def test_session_trade_cap(tmp_path):
    rm = _rm(tmp_path, max_trades_session=2, max_daily_spend_usdc=100)
    rm.record_trade("cond-1", 0.5, _trade())
    rm.record_trade("cond-2", 0.5, _trade())
    assert rm.size_order(1.0) == 0


def test_dedup_already_traded(tmp_path):
    rm = _rm(tmp_path)
    assert rm.already_traded("cond-1") is False
    rm.record_trade("cond-1", 0.5, _trade())
    assert rm.already_traded("cond-1") is True


def test_paused_blocks_everything(tmp_path):
    rm = _rm(tmp_path, paused_check=lambda: True)
    assert rm.size_order(1.0) == 0
    assert rm.kill_switch_active() is True


def test_file_kill_switch_blocks_everything(tmp_path):
    tripped = {"value": False}
    rm = _rm(tmp_path, kill_switch_check=lambda: tripped["value"])
    assert rm.size_order(1.0) == 1.0
    tripped["value"] = True
    assert rm.size_order(1.0) == 0


def test_non_positive_request_is_skipped(tmp_path):
    rm = _rm(tmp_path)
    assert rm.size_order(0) == 0
    assert rm.size_order(-5) == 0


def test_state_persists_across_instances(tmp_path):
    state_file = tmp_path / "state.json"
    rm1 = RiskManager(
        min_trade_usd=0.10, max_trade_usd=1.0, max_trades_session=10,
        max_daily_spend_usdc=5.0, state_file=state_file,
    )
    rm1.record_trade("cond-1", 1.0, _trade(usdc=1.0))

    rm2 = RiskManager(
        min_trade_usd=0.10, max_trade_usd=1.0, max_trades_session=10,
        max_daily_spend_usdc=5.0, state_file=state_file,
    )
    assert rm2.already_traded("cond-1") is True
    assert len(rm2.trades_today()) == 1
    assert rm2.spent_today() == 1.0
