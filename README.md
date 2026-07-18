# Storm

Storm is a Polymarket.US trading bot focused exclusively on weather markets
(temperature, rain, snow, storms, etc). It is a companion to **Colossus**,
a separate bot that trades most sports-league markets — different repo,
different Railway project, but the **same Polymarket.US account/API key**.
Storm's config and structure deliberately mirror Colossus where the
underlying concept is the same, so the two are easy to operate side by
side.

## How it works

Every cycle (`SCAN_INTERVAL`, default 300s), Storm:

1. **Discovers markets** — pulls all active markets from Polymarket's public
   Gamma Markets API (`storm/gamma_client.py`).
2. **Filters to weather** — keyword-matches question/description/tags to
   keep Storm out of Colossus's sports-league territory
   (`storm/market_filter.py`).
3. **Parses the market** — extracts location, weather variable (rain/snow/
   temp above/below a threshold), and target date from the question text
   and the market's `endDate` (`storm/market_parser.py`).
4. **Fetches a forecast** — pulls the relevant NWS (api.weather.gov)
   forecast for that location/date (`storm/weather_client.py`).
5. **Estimates a signal** — compares Storm's probability estimate from the
   forecast against the market's current price; if the edge clears
   `STORM_MIN_EDGE`, it produces a trade signal (`storm/signal_engine.py`).
6. **Trades (or logs)** — the risk manager checks pause/kill-switch state
   and position/session/daily caps, then the trader either logs a dry-run
   line or places a real order via the `polymarket-us` SDK
   (`storm/risk_manager.py`, `storm/trader.py`, `storm/us_client.py`), and
   sends a Telegram alert either way.

Storm places entries and lets markets resolve naturally — there's no
take-profit/stop-loss position management (Colossus has this; weather
markets are short-dated and resolve to a hard 0/1 outcome day-of, so
active exit management adds complexity without much benefit here).

The market-question parser is intentionally conservative: it returns `None`
(skip) rather than guess when it doesn't recognize the phrasing. Extend
`CITY_COORDINATES` and the keyword lists in `storm/market_parser.py` /
`storm/market_filter.py` as you find weather markets Storm misses.

## Sharing a Polymarket.US account with Colossus

Storm and Colossus use the same Polymarket.US API key/account but are
otherwise fully independent (separate repos, separate Railway projects,
separate processes). A few things keep them from interfering with each
other:

- **Market scope**: `storm/market_filter.py`'s keyword filter is what keeps
  Storm out of Colossus's sports markets, and vice versa. There's no
  shared registry — if you see overlap, tighten the keyword lists.
- **Rate limiting**: `storm/rate_limiter.py` is a token-bucket limiter
  applied to every Polymarket call Storm makes (Gamma reads and order
  placement alike — see `main.py`'s single shared `TokenBucketRateLimiter`
  instance). Colossus doesn't run an explicit limiter of its own, so this
  only throttles Storm's own traffic; it does not coordinate with
  Colossus's process. Keep `STORM_MAX_REQUESTS_PER_SECOND` conservative so
  Storm's usage plus Colossus's stays under the account's rate limit.
- **Trade dedup and session caps**: `storm/risk_manager.py` tracks trades
  per calendar day (persisted to `storm_daily_state.json`) so Storm never
  re-fires on a market it already traded today, and caps itself at
  `MAX_TRADES_SESSION` — independent of whatever Colossus is doing.

## Trading safety

- **Dry-run by default.** `LIVE_TRADING` defaults to `false` — Storm scans
  markets and logs (and Telegram-alerts) exactly what it *would* trade
  without sending any orders. Set `LIVE_TRADING=true` (e.g. as a Railway
  variable) once you've verified its behavior.
- **Pause, two ways**: set `PAUSED=true` (env var, needs a redeploy/restart)
  or send `/pause` to Storm's Telegram bot (takes effect immediately, and
  `/resume` reverses it). Either stops Storm from opening new trades.
- **Kill-switch file**: independent of `PAUSED`/Telegram — if the file
  named by `STORM_KILL_SWITCH_FILE` (default `storm.kill`) exists on disk,
  Storm halts new trades on its next cycle. Useful if Telegram is down.
- **Hard caps**: `MAX_TRADE_USD` caps every individual trade,
  `MAX_TRADES_SESSION` caps trades per day, `STORM_MAX_DAILY_SPEND_USDC`
  caps total $ spent per day, and `MIN_TRADE_USD` skips trades too small to
  bother placing. All enforced in `storm/risk_manager.py` regardless of
  signal confidence.

## Telegram

Storm runs its own Telegram bot (separate token/chat from Colossus's) for
alerts and control:

- Sends a startup message, and an alert for every signal (dry-run or live).
- Commands: `/status` (mode, pause state, trades/spend today), `/pause`,
  `/resume`, `/report` (today's trades).
- Implemented with plain HTTPS calls to the Telegram Bot API
  (`storm/telegram_bot.py`) polled from a background thread
  (`storm/telegram_commands.py`) — Storm stays synchronous rather than
  adopting Colossus's async (aiohttp/APScheduler) style.

If `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` are left blank, Storm just skips
Telegram entirely and relies on stdout logs.

## Project layout

```
main.py                   entrypoint: builds the bot, runs the poll loop
storm/
  config.py                env-var driven configuration
  logging_config.py
  rate_limiter.py           shared token-bucket limiter
  gamma_client.py           Polymarket Gamma Markets API (market discovery)
  market_filter.py          weather keyword filter
  market_parser.py          question/description -> WeatherMarketSpec
  weather_client.py         NWS (api.weather.gov) forecast client
  signal_engine.py          forecast + market price -> TradeSignal
  risk_manager.py           pause/kill-switch + position/session/daily caps
  us_client.py              polymarket-us SDK wrapper, rate-limited
  trader.py                 executes signals (dry-run or live) + Telegram alert
  telegram_bot.py           minimal Telegram Bot API client (plain HTTPS)
  telegram_commands.py      background thread handling /status /pause /resume /report
  bot.py                    orchestrates one scan-and-trade cycle
tests/                      unit tests (no network calls)
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # fill in credentials for local runs
pytest
python main.py
```

## Environment variables

See `.env.example` for the full list with defaults. Notable ones:

| Variable | Purpose |
|---|---|
| `POLYMARKET_KEY_ID`, `POLYMARKET_SECRET_KEY` | Polymarket.US API credentials (same account as Colossus). Required only when `LIVE_TRADING=true`. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Storm's own Telegram bot for alerts/commands. Leave blank to disable. |
| `LIVE_TRADING` | `false` (default) = dry-run/log only. `true` = place real orders. |
| `PAUSED` | Stop opening new trades (env var or Telegram `/pause` `/resume`). |
| `STORM_KILL_SWITCH_FILE` | File-based failsafe, independent of Telegram. |
| `MIN_TRADE_USD`, `MAX_TRADE_USD`, `MAX_TRADES_SESSION` | Trading caps (same names/semantics as Colossus). |
| `STORM_MAX_DAILY_SPEND_USDC` | Storm-only extra daily $ cap. |
| `STORM_MIN_EDGE` | Minimum estimated-probability vs. market-price gap required to trade. |
| `STORM_MAX_REQUESTS_PER_SECOND`, `STORM_RATE_LIMITER_BURST` | Storm's self-throttle share of the shared Polymarket account's rate limit. |
| `NWS_USER_AGENT` | Required by NWS's usage policy — set to something identifying (e.g. an email). |

## Deploying to Railway

This repo is set up for a Railway **worker** service (no HTTP port needed):

- `Procfile` / `railway.json` run `python main.py` on start, restarting on
  failure.
- Set all variables from `.env.example` as Railway project variables
  (never commit a real `.env`).
- Deploy with `LIVE_TRADING=false` first, watch the logs/Telegram for a
  few cycles of dry-run output, then flip `LIVE_TRADING=true` once you're
  satisfied.
- `RAILWAY_DEPLOYMENT_OVERLAP_SECONDS` (visible on Colossus's Railway
  service) is a Railway platform setting, not something Storm's code
  reads — set it directly in Railway's service settings if you want to
  control the zero-downtime deploy overlap window.

## Testing

```bash
pytest
```

All tests are pure unit tests (rate limiter timing, risk manager caps/
persistence, market filter/parser, signal engine, Telegram command
handling) — no network calls, so they run the same locally and in CI.
