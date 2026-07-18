"""Storm entrypoint: runs the scan-and-trade loop on a fixed interval."""

from __future__ import annotations

import logging
import time

from storm.bot import StormBot
from storm.clob_client import RateLimitedClobClient, build_clob_client
from storm.config import config
from storm.gamma_client import GammaClient
from storm.logging_config import setup_logging
from storm.rate_limiter import TokenBucketRateLimiter
from storm.risk_manager import RiskManager, file_kill_switch
from storm.trader import Trader
from storm.weather_client import NWSClient

logger = logging.getLogger(__name__)


def build_bot() -> StormBot:
    # Single rate limiter shared across every Polymarket call (Gamma reads
    # and CLOB order calls alike) since they hit the same account as Colossus.
    rate_limiter = TokenBucketRateLimiter(config.MAX_REQUESTS_PER_SECOND, config.RATE_LIMITER_BURST)
    gamma_client = GammaClient(config.GAMMA_HOST, rate_limiter)
    weather_client = NWSClient(config.NWS_USER_AGENT)

    clob_client = None
    if config.LIVE_TRADING:
        if not config.POLYMARKET_PRIVATE_KEY or not config.POLYMARKET_FUNDER_ADDRESS:
            raise RuntimeError(
                "LIVE_TRADING is enabled but POLYMARKET_PRIVATE_KEY/POLYMARKET_FUNDER_ADDRESS are not set"
            )
        raw_client = build_clob_client(
            config.CLOB_HOST,
            config.CHAIN_ID,
            config.POLYMARKET_PRIVATE_KEY,
            config.POLYMARKET_FUNDER_ADDRESS,
            config.POLYMARKET_API_KEY,
            config.POLYMARKET_API_SECRET,
            config.POLYMARKET_API_PASSPHRASE,
        )
        clob_client = RateLimitedClobClient(raw_client, rate_limiter)

    risk_manager = RiskManager(
        max_position_usdc=config.MAX_POSITION_USDC,
        max_daily_spend_usdc=config.MAX_DAILY_SPEND_USDC,
        kill_switch_env=config.KILL_SWITCH,
        kill_switch_check=file_kill_switch(config.KILL_SWITCH_FILE),
    )

    trader = Trader(
        clob_client=clob_client,
        risk_manager=risk_manager,
        live_trading=config.LIVE_TRADING,
        default_order_usdc=config.MAX_POSITION_USDC,
    )

    return StormBot(gamma_client, weather_client, trader, config.MIN_EDGE)


def main() -> None:
    setup_logging(config.LOG_LEVEL)
    logger.info(
        "Starting Storm (live_trading=%s, poll_interval=%ss, max_rps=%.1f)",
        config.LIVE_TRADING,
        config.POLL_INTERVAL_SECONDS,
        config.MAX_REQUESTS_PER_SECOND,
    )
    bot = build_bot()

    while True:
        try:
            bot.run_cycle()
        except Exception:
            logger.exception("Unhandled error during Storm cycle")
        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
