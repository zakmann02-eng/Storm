"""Storm entrypoint: runs the scan-and-trade loop on a fixed interval."""

from __future__ import annotations

import logging
import time

from storm.bot import StormBot
from storm.config import config
from storm.dashboard import DashboardServer
from storm.dashboard_state import DashboardState
from storm.gamma_client import GammaClient
from storm.logging_config import setup_logging
from storm.openmeteo_client import OpenMeteoClient
from storm.rate_limiter import TokenBucketRateLimiter
from storm.risk_manager import RiskManager, file_kill_switch
from storm.telegram_bot import TelegramNotifier
from storm.telegram_commands import TelegramCommandListener
from storm.trader import Trader
from storm.us_client import USClient
from storm.weather_client import NWSClient

logger = logging.getLogger(__name__)


def build_bot() -> tuple[StormBot, TelegramCommandListener, TelegramNotifier, DashboardState]:
    # Single rate limiter shared across every Polymarket call (Gamma reads
    # and order placement alike) since they hit the same account as Colossus.
    rate_limiter = TokenBucketRateLimiter(config.MAX_REQUESTS_PER_SECOND, config.RATE_LIMITER_BURST)
    gamma_client = GammaClient(config.GAMMA_HOST, rate_limiter)
    weather_client = NWSClient(config.NWS_USER_AGENT)
    # Second forecast source blended into signal_engine's estimate for a
    # small ensemble instead of relying solely on NWS's single model.
    # Free/keyless, and best-effort - see StormBot._get_open_meteo_forecast.
    open_meteo_client = OpenMeteoClient()
    notifier = TelegramNotifier(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)

    # Required even in dry-run: market discovery goes through the
    # polymarket-us SDK (see storm/us_client.py's list_markets), not just
    # order placement, since Polymarket.US's own markets - including the
    # "Temp" weather category - aren't served by the generic Gamma API.
    if not config.POLYMARKET_KEY_ID or not config.POLYMARKET_SECRET_KEY:
        raise RuntimeError("POLYMARKET_KEY_ID/POLYMARKET_SECRET_KEY are not set")
    us_client = USClient(config.POLYMARKET_KEY_ID, config.POLYMARKET_SECRET_KEY, rate_limiter)

    risk_manager = RiskManager(
        min_trade_usd=config.MIN_TRADE_USD,
        max_trade_usd=config.MAX_TRADE_USD,
        max_trades_session=config.MAX_TRADES_SESSION,
        max_daily_spend_usdc=config.MAX_DAILY_SPEND_USDC,
        kill_switch_check=file_kill_switch(config.KILL_SWITCH_FILE),
    )

    trader = Trader(
        us_client=us_client,
        risk_manager=risk_manager,
        notifier=notifier,
        live_trading=config.LIVE_TRADING,
        default_order_usdc=config.MAX_TRADE_USD,
        kelly_multiplier=config.KELLY_MULTIPLIER,
    )

    # Dashboard is purely additive - the scan/trade loop above is built and
    # run identically whether or not it's enabled; this just gives StormBot
    # somewhere to record what it's already doing.
    dashboard_state = DashboardState()

    bot = StormBot(
        us_client, gamma_client, weather_client, trader, risk_manager, config.MIN_EDGE,
        open_meteo_client=open_meteo_client,
        diagnostic_probe_slug=config.DIAGNOSTIC_PROBE_SLUG,
        dashboard_state=dashboard_state,
    )

    command_listener = TelegramCommandListener(
        notifier=notifier,
        risk_manager=risk_manager,
        live_trading=config.LIVE_TRADING,
        max_trade_usd=config.MAX_TRADE_USD,
        max_trades_session=config.MAX_TRADES_SESSION,
        max_daily_spend_usdc=config.MAX_DAILY_SPEND_USDC,
        min_edge=config.MIN_EDGE,
    )

    return bot, command_listener, notifier, dashboard_state


def main() -> None:
    setup_logging(config.LOG_LEVEL)
    logger.info(
        "Starting Storm (live_trading=%s, scan_interval=%ss, max_rps=%.1f)",
        config.LIVE_TRADING,
        config.SCAN_INTERVAL,
        config.MAX_REQUESTS_PER_SECOND,
    )
    bot, command_listener, notifier, dashboard_state = build_bot()
    command_listener.start()

    if config.DASHBOARD_ENABLED:
        DashboardServer(dashboard_state, port=config.DASHBOARD_PORT).start()
    else:
        logger.info("Dashboard disabled (STORM_DASHBOARD_ENABLED=false)")

    mode = "LIVE trading" if config.LIVE_TRADING else "Dry-run (no real orders)"
    notifier.send(
        f"Storm online\nMode: {mode}\nScanning every {config.SCAN_INTERVAL}s\n"
        f"Trade range: ${config.MIN_TRADE_USD:.2f}-${config.MAX_TRADE_USD:.2f}\n"
        "Commands: /status /pause /resume /report"
    )

    while True:
        try:
            bot.run_cycle()
        except Exception:
            logger.exception("Unhandled error during Storm cycle")
        time.sleep(config.SCAN_INTERVAL)


if __name__ == "__main__":
    main()
