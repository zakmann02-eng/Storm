"""Environment-driven configuration for Storm.

Variable names intentionally mirror Colossus (the sports-trading bot that
shares this Polymarket.US account) where the concept is the same, so the
two Railway projects are easy to reason about side by side:
POLYMARKET_KEY_ID/SECRET_KEY, MIN_TRADE_USD/MAX_TRADE_USD,
MAX_TRADES_SESSION, PAUSED, SCAN_INTERVAL. Vars with no Colossus
equivalent (Storm's own dry-run switch, daily $ cap, signal edge
threshold, and self-throttle) keep a STORM_ prefix.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _get_float(name: str, default: float) -> float:
    val = os.environ.get(name)
    return float(val) if val else default


def _get_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    return int(val) if val else default


class Config:
    # --- Polymarket.US credentials (shared with Colossus - same account) ---
    POLYMARKET_KEY_ID: str = os.environ.get("POLYMARKET_KEY_ID", "")
    POLYMARKET_SECRET_KEY: str = os.environ.get("POLYMARKET_SECRET_KEY", "")
    GAMMA_HOST: str = os.environ.get("GAMMA_HOST", "https://gamma-api.polymarket.com")

    # --- Telegram (Storm's own bot - separate from Colossus's) ---
    TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")

    # --- Rate limiting ---
    # Storm's own conservative slice of the shared account rate limit.
    # Colossus doesn't run an explicit limiter of its own; this only
    # throttles Storm's traffic, so keep it low enough that Storm's usage
    # plus Colossus's stays under Polymarket's account-wide limit.
    MAX_REQUESTS_PER_SECOND: float = _get_float("STORM_MAX_REQUESTS_PER_SECOND", 2.0)
    RATE_LIMITER_BURST: int = _get_int("STORM_RATE_LIMITER_BURST", 4)

    # --- Trading safety ---
    LIVE_TRADING: bool = _get_bool("LIVE_TRADING", False)
    PAUSED: bool = _get_bool("PAUSED", False)
    # Extra failsafe independent of PAUSED/Telegram: if this file exists on
    # disk, Storm halts new trades on its next cycle, no restart needed.
    KILL_SWITCH_FILE: str = os.environ.get("STORM_KILL_SWITCH_FILE", "storm.kill")

    MIN_TRADE_USD: float = _get_float("MIN_TRADE_USD", 0.10)
    MAX_TRADE_USD: float = _get_float("MAX_TRADE_USD", 1.00)
    MAX_TRADES_SESSION: int = _get_int("MAX_TRADES_SESSION", 10)
    # Storm-only extra guard beyond Colossus's per-trade-count cap.
    MAX_DAILY_SPEND_USDC: float = _get_float("STORM_MAX_DAILY_SPEND_USDC", 5.00)
    MIN_EDGE: float = _get_float("STORM_MIN_EDGE", 0.08)
    # Fractional Kelly - position size scales with edge/confidence rather
    # than always requesting a flat MAX_TRADE_USD. 0.5 = half-Kelly, a
    # common practical safety margin against probability-estimate error;
    # the result still passes through MIN/MAX_TRADE_USD and the daily/
    # session caps above, so this never sizes beyond those limits.
    KELLY_MULTIPLIER: float = _get_float("STORM_KELLY_MULTIPLIER", 0.5)

    # --- Weather data ---
    NWS_USER_AGENT: str = os.environ.get(
        "NWS_USER_AGENT", "storm-weather-bot (set NWS_USER_AGENT env var with contact info)"
    )

    SCAN_INTERVAL: int = _get_int("SCAN_INTERVAL", 120)
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")


config = Config()
