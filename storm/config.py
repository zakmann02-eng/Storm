"""Environment-driven configuration for Storm.

All tunables live here so behavior can be changed via Railway environment
variables without touching code.
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
    # --- Polymarket credentials (shared with Colossus - same account/key) ---
    POLYMARKET_PRIVATE_KEY: str = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
    POLYMARKET_FUNDER_ADDRESS: str = os.environ.get("POLYMARKET_FUNDER_ADDRESS", "")
    POLYMARKET_API_KEY: str = os.environ.get("POLYMARKET_API_KEY", "")
    POLYMARKET_API_SECRET: str = os.environ.get("POLYMARKET_API_SECRET", "")
    POLYMARKET_API_PASSPHRASE: str = os.environ.get("POLYMARKET_API_PASSPHRASE", "")

    CLOB_HOST: str = os.environ.get("CLOB_HOST", "https://clob.polymarket.com")
    GAMMA_HOST: str = os.environ.get("GAMMA_HOST", "https://gamma-api.polymarket.com")
    CHAIN_ID: int = _get_int("CHAIN_ID", 137)

    # --- Rate limiting ---
    # Storm's own conservative slice of the shared account rate limit.
    # Colossus enforces its own limiter independently against the same key;
    # this does not coordinate with Colossus's process, it just keeps
    # Storm's share low so the two together stay under Polymarket's limit.
    MAX_REQUESTS_PER_SECOND: float = _get_float("STORM_MAX_REQUESTS_PER_SECOND", 2.0)
    RATE_LIMITER_BURST: int = _get_int("STORM_RATE_LIMITER_BURST", 4)

    # --- Trading safety ---
    LIVE_TRADING: bool = _get_bool("LIVE_TRADING", False)
    KILL_SWITCH: bool = _get_bool("STORM_KILL_SWITCH", False)
    KILL_SWITCH_FILE: str = os.environ.get("STORM_KILL_SWITCH_FILE", "storm.kill")
    MAX_POSITION_USDC: float = _get_float("STORM_MAX_POSITION_USDC", 25.0)
    MAX_DAILY_SPEND_USDC: float = _get_float("STORM_MAX_DAILY_SPEND_USDC", 100.0)
    MIN_EDGE: float = _get_float("STORM_MIN_EDGE", 0.08)

    # --- Weather data ---
    NWS_USER_AGENT: str = os.environ.get(
        "NWS_USER_AGENT", "storm-weather-bot (set NWS_USER_AGENT env var with contact info)"
    )

    POLL_INTERVAL_SECONDS: int = _get_int("STORM_POLL_INTERVAL_SECONDS", 300)
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")


config = Config()
