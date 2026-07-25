# Storm

Storm is a Polymarket.US trading bot focused exclusively on weather markets
(temperature, rain, snow, storms, etc). It is a companion to **Colossus**,
a separate bot that trades most sports-league markets — different repo,
different Railway project, but the **same Polymarket.US account/API key**.
Storm's config and structure deliberately mirror Colossus where the
underlying concept is the same, so the two are easy to operate side by
side.

## How it works

Every cycle (`SCAN_INTERVAL`, default 120s), Storm:

1. **Discovers markets** — pulls active markets via the `polymarket-us`
   SDK's `events.list()` -> `/v1/events` (`storm/us_client.py`'s
   `list_markets`), the same endpoint and method Colossus uses. The real
   bug history here matters: an early version stopped paginating as soon
   as a page came back shorter than the requested limit, which happened
   to reliably truncate the scan at ~2,599 items (all sports) every time.
   Confirmed against Colossus's own production logs, this endpoint's
   pagination is irregular — short pages can appear mid-stream with
   thousands more results following them. The real total is ~25,000+
   items, and Temp/weather markets live well past where the old code gave
   up. The fix (and Colossus's own working approach) is to keep
   paginating until a page comes back genuinely *empty*. Polymarket.US's
   own markets also aren't served by the generic public Gamma API, so
   that (`storm/gamma_client.py`) is kept only as a fallback if the SDK
   call fails or returns nothing.
2. **Filters to weather** — checks for an exact match against
   Polymarket.US's "Temp" category/tag first, then a structured
   "is this definitely sports?" check (`sportsMarketType`, or a tag
   carrying `sport`/`league` — both confirmed straight from Polymarket.US's
   own OpenAPI schema), then falls back to keyword-matching
   question/description/tags — to keep Storm out of Colossus's
   sports-league territory (`storm/market_filter.py`).
3. **Parses the market** — extracts location, weather variable (rain/snow/
   temp above/below a threshold), and target date from the question text
   and the market's `endDate` (`storm/market_parser.py`). Pricing comes
   from `storm/market_pricing.py`, which prefers the modern `marketSides`
   (long/short) representation and falls back to the legacy `outcomePrices`
   field — Polymarket.US's own OpenAPI schema marks `outcomePrices` (and
   `conditionId`, replaced by `id`) as deprecated, so relying on those
   alone risks silently skipping real markets. Note: some
   weather questions (e.g. "Highest temperature in NYC on July 18?") are
   grouped Polymarket events with several range-bucket outcomes ("78 or
   below", "79 to 80", ...) rather than one simple threshold.
   `storm/bot.py` logs the raw JSON of the first several markets the
   parser can't handle (capped, so it can't spam logs) specifically to
   help extend the parser for shapes like this. The probability math for
   range-bucket markets already exists and is fully tested
   (`storm/bucket_signal.py` — models the forecast as a normal
   distribution and integrates it over each bucket's range) but isn't
   wired into discovery yet, pending real field names for how Polymarket.US
   represents a bucket's range boundaries within a grouped event.
4. **Fetches a forecast** — pulls NWS's (api.weather.gov) forecast for that
   location/date (`storm/weather_client.py`), plus a second, free/keyless
   forecast from Open-Meteo (`storm/openmeteo_client.py`), which itself
   blends multiple weather models (GFS, ECMWF, ICON, ...).
5. **Estimates a signal** — averages the NWS and Open-Meteo estimates (a
   small ensemble rather than one model's point forecast - either source
   alone still works fine if the other is unavailable) and compares that
   against the market's current price; if the edge clears `STORM_MIN_EDGE`,
   it produces a trade signal (`storm/signal_engine.py`).
6. **Trades (or logs)** — the risk manager checks pause/kill-switch state
   and position/session/daily caps, then the trader either logs a dry-run
   line or places a real order via the `polymarket-us` SDK
   (`storm/risk_manager.py`, `storm/trader.py`, `storm/us_client.py`), and
   sends a Telegram alert either way. Position size is Kelly-derived from
   the live account balance (`storm/position_sizing.py`, half-Kelly by
   default via `STORM_KELLY_MULTIPLIER`) rather than a flat dollar amount —
   stronger edges size up, weaker ones size down — still bounded by
   `MIN_TRADE_USD`/`MAX_TRADE_USD` and the daily/session caps.

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
- **Live balance check before every real order**: neither bot knows what
  the other is doing in real time, so `storm/trader.py` pulls the actual
  account balance from the Polymarket.US SDK right before placing a live
  order and skips the trade if the shared account can't currently cover
  it (e.g. Colossus has funds tied up in open positions). This only
  applies when `LIVE_TRADING=true` — dry-run doesn't touch the real
  balance.

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
  gamma_client.py           Polymarket Gamma Markets API (discovery fallback)
  market_filter.py          weather keyword/category/structured filter
  market_parser.py          question/description -> WeatherMarketSpec
  market_pricing.py         marketSides/outcomePrices -> [yes_price, no_price]
  weather_client.py         NWS (api.weather.gov) forecast client
  openmeteo_client.py       Open-Meteo forecast client (second ensemble source)
  signal_engine.py          blended forecast + market price -> TradeSignal
  bucket_signal.py          range-bucket probability math (not yet wired in)
  position_sizing.py        Kelly-criterion position sizing
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
| `POLYMARKET_KEY_ID`, `POLYMARKET_SECRET_KEY` | Polymarket.US API credentials (same account as Colossus). Always required, even in dry-run - market discovery goes through the SDK, not just order placement. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Storm's own Telegram bot for alerts/commands. Leave blank to disable. |
| `LIVE_TRADING` | `false` (default) = dry-run/log only. `true` = place real orders. |
| `PAUSED` | Stop opening new trades (env var or Telegram `/pause` `/resume`). |
| `STORM_KILL_SWITCH_FILE` | File-based failsafe, independent of Telegram. |
| `MIN_TRADE_USD`, `MAX_TRADE_USD`, `MAX_TRADES_SESSION` | Trading caps (same names/semantics as Colossus). |
| `STORM_MAX_DAILY_SPEND_USDC` | Storm-only extra daily $ cap. |
| `STORM_MIN_EDGE` | Minimum estimated-probability vs. market-price gap required to trade. |
| `STORM_KELLY_MULTIPLIER` | Fractional Kelly for position sizing (0.5 = half-Kelly default). Still bounded by `MIN_TRADE_USD`/`MAX_TRADE_USD`. |
| `STORM_MAX_REQUESTS_PER_SECOND`, `STORM_RATE_LIMITER_BURST` | Storm's self-throttle share of the shared Polymarket account's rate limit. |
| `NWS_USER_AGENT` | Required by NWS's usage policy — set to something identifying (e.g. an email). |
| *(none)* | Open-Meteo needs no env var — free, keyless, used automatically as a second forecast source. |

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
