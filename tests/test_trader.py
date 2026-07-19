import datetime as dt

from storm.market_parser import WeatherMarketSpec
from storm.risk_manager import RiskManager
from storm.signal_engine import TradeSignal
from storm.trader import Trader


class _FakeUSClient:
    def __init__(self, balance: float):
        self.balance = balance
        self.orders_placed = []

    def get_balance(self) -> float:
        return self.balance

    def place_order(self, market_slug, side, price, amount_usd):
        self.orders_placed.append((market_slug, side, price, amount_usd))
        return {"status": "accepted"}


class _FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)


def _risk_manager(tmp_path, **overrides):
    defaults = dict(
        min_trade_usd=0.10,
        max_trade_usd=1.00,
        max_trades_session=10,
        max_daily_spend_usdc=5.00,
        state_file=tmp_path / "state.json",
    )
    defaults.update(overrides)
    return RiskManager(**defaults)


def _signal(yes_price=0.2):
    spec = WeatherMarketSpec(
        condition_id="0xabc",
        market_slug="nyc-rain",
        question="Will it rain in New York City?",
        location="new york city",
        lat=40.7128,
        lon=-74.0060,
        variable="rain",
        threshold=None,
        target_date=dt.date(2026, 7, 20),
        yes_price=yes_price,
    )
    return TradeSignal(market=spec, side="YES", estimated_probability=0.9, market_probability=yes_price, edge=0.7)


def test_live_trade_skipped_when_balance_too_low(tmp_path):
    us_client = _FakeUSClient(balance=0.05)
    notifier = _FakeNotifier()
    risk_manager = _risk_manager(tmp_path)
    trader = Trader(us_client, risk_manager, notifier, live_trading=True, default_order_usdc=1.00)

    trader.execute(_signal())

    assert us_client.orders_placed == []
    # Balance check fails before any Telegram alert or risk-manager record.
    assert notifier.sent == []
    assert risk_manager.trades_today() == []


def test_live_trade_placed_when_balance_sufficient(tmp_path):
    us_client = _FakeUSClient(balance=10.0)
    notifier = _FakeNotifier()
    risk_manager = _risk_manager(tmp_path)
    trader = Trader(us_client, risk_manager, notifier, live_trading=True, default_order_usdc=1.00)

    trader.execute(_signal())

    assert len(us_client.orders_placed) == 1
    assert len(notifier.sent) == 1
    assert len(risk_manager.trades_today()) == 1


def test_dry_run_uses_kelly_sizing_but_skips_the_live_balance_gate(tmp_path):
    # Dry-run still fetches bankroll and Kelly-sizes off it (for a
    # realistic simulation) but never reaches the live-only
    # insufficient-balance check or places a real order.
    us_client = _FakeUSClient(balance=10.0)
    notifier = _FakeNotifier()
    risk_manager = _risk_manager(tmp_path)
    trader = Trader(us_client, risk_manager, notifier, live_trading=False, default_order_usdc=1.00)

    trader.execute(_signal())

    assert us_client.orders_placed == []
    assert len(notifier.sent) == 1
    assert len(risk_manager.trades_today()) == 1


def test_kelly_sizing_scales_with_bankroll(tmp_path):
    notifier = _FakeNotifier()

    rm_small = _risk_manager(tmp_path, max_trade_usd=100, state_file=tmp_path / "small.json")
    trader_small = Trader(_FakeUSClient(balance=1.0), rm_small, notifier, live_trading=False, default_order_usdc=1.00)
    trader_small.execute(_signal())

    rm_big = _risk_manager(tmp_path, max_trade_usd=100, state_file=tmp_path / "big.json")
    trader_big = Trader(_FakeUSClient(balance=100.0), rm_big, notifier, live_trading=False, default_order_usdc=1.00)
    trader_big.execute(_signal())

    small_trade = rm_small.trades_today()[0]
    big_trade = rm_big.trades_today()[0]
    assert big_trade["usdc"] > small_trade["usdc"]


def test_kelly_sizing_is_zero_bankroll_safe(tmp_path):
    # A $0 (or unreadable) bankroll should cleanly skip, not error.
    us_client = _FakeUSClient(balance=0.0)
    notifier = _FakeNotifier()
    risk_manager = _risk_manager(tmp_path)
    trader = Trader(us_client, risk_manager, notifier, live_trading=False, default_order_usdc=1.00)

    trader.execute(_signal())

    assert notifier.sent == []
    assert risk_manager.trades_today() == []
