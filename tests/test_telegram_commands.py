import os

from storm.risk_manager import RiskManager
from storm.telegram_commands import TelegramCommandListener


class _FakeNotifier:
    def __init__(self):
        self.enabled = True
        self.sent = []

    def send(self, text):
        self.sent.append(text)


def _listener(tmp_path, notifier=None):
    rm = RiskManager(
        min_trade_usd=0.10,
        max_trade_usd=1.00,
        max_trades_session=10,
        max_daily_spend_usdc=5.00,
        state_file=tmp_path / "state.json",
    )
    return TelegramCommandListener(
        notifier=notifier or _FakeNotifier(),
        risk_manager=rm,
        live_trading=False,
        max_trade_usd=1.00,
        max_trades_session=10,
        max_daily_spend_usdc=5.00,
        min_edge=0.08,
    ), rm


def test_pause_and_resume_set_env_var(tmp_path, monkeypatch):
    monkeypatch.delenv("PAUSED", raising=False)
    notifier = _FakeNotifier()
    listener, _ = _listener(tmp_path, notifier)

    listener._handle_command("/pause")
    assert os.environ["PAUSED"] == "true"

    listener._handle_command("/resume")
    assert os.environ["PAUSED"] == "false"
    assert len(notifier.sent) == 2


def test_status_reports_current_state(tmp_path, monkeypatch):
    monkeypatch.setenv("PAUSED", "false")
    notifier = _FakeNotifier()
    listener, _ = _listener(tmp_path, notifier)

    listener._handle_command("/status")
    assert len(notifier.sent) == 1
    assert "Paused: no" in notifier.sent[0]
    assert "dry-run" in notifier.sent[0]


def test_report_with_no_trades(tmp_path):
    notifier = _FakeNotifier()
    listener, _ = _listener(tmp_path, notifier)

    listener._handle_command("/report")
    assert notifier.sent == ["No trades recorded today."]


def test_report_lists_recorded_trades(tmp_path):
    notifier = _FakeNotifier()
    listener, rm = _listener(tmp_path, notifier)
    rm.record_trade("cond-1", 0.5, {"side": "YES", "question": "Will it rain?", "price": 0.4, "usdc": 0.5})

    listener._handle_command("/report")
    assert "YES" in notifier.sent[0]
    assert "Will it rain?" in notifier.sent[0]


def test_command_with_bot_mention_suffix_is_handled(tmp_path):
    notifier = _FakeNotifier()
    listener, _ = _listener(tmp_path, notifier)

    listener._handle_command("/status@StormBot")
    assert len(notifier.sent) == 1
