from storm.risk_manager import RiskManager


def test_caps_to_max_position():
    rm = RiskManager(max_position_usdc=10, max_daily_spend_usdc=1000)
    assert rm.size_order(50) == 10


def test_caps_to_remaining_daily_budget():
    rm = RiskManager(max_position_usdc=100, max_daily_spend_usdc=15)
    assert rm.size_order(50) == 15
    rm.record_spend(15)
    assert rm.size_order(50) == 0


def test_kill_switch_env_blocks_everything():
    rm = RiskManager(max_position_usdc=100, max_daily_spend_usdc=100, kill_switch_env=True)
    assert rm.size_order(10) == 0
    assert rm.kill_switch_active() is True


def test_kill_switch_file_blocks_everything():
    tripped = {"value": False}
    rm = RiskManager(
        max_position_usdc=100,
        max_daily_spend_usdc=100,
        kill_switch_check=lambda: tripped["value"],
    )
    assert rm.size_order(10) == 10
    tripped["value"] = True
    assert rm.size_order(10) == 0


def test_non_positive_request_is_skipped():
    rm = RiskManager(max_position_usdc=100, max_daily_spend_usdc=100)
    assert rm.size_order(0) == 0
    assert rm.size_order(-5) == 0
