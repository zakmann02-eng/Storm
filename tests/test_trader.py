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


def test_dry_run_does_not_check_balance(tmp_path):
    us_client = _FakeUSClient(balance=0.0)
    notifier = _FakeNotifier()
    risk_manager = _risk_manager(tmp_path)
    trader = Trader(us_client, risk_manager, notifier, live_trading=False, default_order_usdc=1.00)

    trader.execute(_signal())

    assert us_client.orders_placed == []
    assert len(notifier.sent) == 1
    assert len(risk_manager.trades_today()) == 1
