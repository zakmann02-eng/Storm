# Storm

Storm is a Polymarket.US weather analyzer and autonomous trading bot. It
tracks exactly three locations — **MIA** (Miami International), **ORD**
(Chicago O'Hare International), and **LAX** (Los Angeles International) —
and ships with a real-time dashboard (live forecasts, market signals/edge,
trade history) alongside its unchanged autonomous scan-and-trade loop. It
is a companion to **Colossus**, a separate bot that trades most
sports-league markets — different repo, different Railway project, but the
**same Polymarket.US account/API key**. Storm's config and structure
deliberately mirror Colossus where the underlying concept is the same, so
the two are easy to operate side by side.

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
3. **Parses the market** — two paths, tried in order:
   - **Range-bucket markets** (`storm/tc_temp_parser.py`): Polymarket.US's
     real `tc-temp-{airport}{high|low}-{date}-gte{low}lt{high}f` slug
     format, confirmed from production data (e.g.
     `tc-temp-mdwhigh-2026-07-25-gte82lt83f` = daily high, July 25 2026,
     bucket [82, 83)°F). The slug directly encodes the bucket's exact
     boundaries, so it's parsed with a regex rather than guessed at from
     free text. Priced via `storm/bucket_signal.py` — models the day's
     forecast as a normal distribution and integrates it over the bucket's
     `[low, high)` range to get Storm's own estimated probability, then
     compares that to the bucket's market price.
   - **Everything else** (rain/snow, or threshold-phrased markets):
     `storm/market_parser.py` extracts location, weather variable, and
     target date from the question text and the market's `endDate`.
   Pricing comes from `storm/market_pricing.py`, which prefers the modern
   `marketSides` (long/short) representation and falls back to the legacy
   `outcomePrices` field — Polymarket.US's own OpenAPI schema marks
   `outcomePrices` (and `conditionId`, replaced by `id`) as deprecated, so
   relying on those alone risks silently skipping real markets.
   Both paths are restricted to the three tracked airports
   (`storm/airports.py`) — Storm no longer monitors a broader city list.
   `storm/bot.py` logs the raw JSON of the first several markets neither
   path can parse (capped, so it can't spam logs), to help extend the
   parsers for shapes Storm is still missing.
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
`storm/airports.py`'s alias list and the keyword lists in
`storm/market_parser.py` / `storm/market_filter.py` as you find weather
markets Storm misses for MIA/ORD/LAX.

> **Note on Chicago:** Storm tracks ORD (O'Hare) per explicit choice, but
> real production `tc-temp-*` slugs observed so far use `mdw` (Midway), a
> different station in the same city. If Storm shows no Chicago-specific
> range-bucket activity, that's why — add an `"mdw"` entry to
> `storm/airports.py`'s `AIRPORTS` dict (same city, different station) if
> Midway-based markets should be tracked instead of/alongside O'Hare.

## Dashboard

Storm serves a real-time, read-only dashboard alongside its unchanged
autonomous scan-and-trade loop — additive only, it never gates or delays a
trade (`storm/dashboard.py`, `storm/dashboard_state.py`):

- **`GET /`** — a single auto-refreshing page (polls every 5s) showing, per
  airport: the latest blended/NWS/Open-Meteo forecast, every market
  currently tracked with its computed signal/edge, and a table of recent
  trade signals.
- **`GET /api/state`** — the same data as JSON, for any external consumer.
- **`GET /healthz`** — plain liveness check (used by Railway's health
  check, see below).

It runs on its own daemon thread (`storm/dashboard.py`'s `DashboardServer`,
uvicorn) — the same pattern as the Telegram command listener — since
Storm's main loop is a plain synchronous `while True` rather than
asyncio-based. `storm/bot.py` records every weather fetch, every market it
evaluates (whether or not a signal fires), and every trade signal into a
thread-safe `DashboardState` (`storm/dashboard_state.py`) as it works
through its normal cycle; the dashboard just reads a locked snapshot of
that state. Set `STORM_DASHBOARD_ENABLED=false` to disable it entirely.

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
main.py                   entrypoint: builds the bot, starts the dashboard, runs the poll loop
storm/
  config.py                env-var driven configuration
  logging_config.py
  rate_limiter.py           shared token-bucket limiter
  airports.py               the three tracked airports (MIA/ORD/LAX) + alias lookup
  gamma_client.py           Polymarket Gamma Markets API (discovery fallback)
  market_filter.py          weather keyword/category/structured filter
  tc_temp_parser.py         parses real "tc-temp-*" range-bucket market slugs
  market_parser.py          question/description -> WeatherMarketSpec (non-bucket markets)
  market_pricing.py         marketSides/outcomePrices -> [yes_price, no_price]
  weather_client.py         NWS (api.weather.gov) forecast client
  openmeteo_client.py       Open-Meteo forecast client (second ensemble source)
  signal_engine.py          blended forecast + market price -> TradeSignal (non-bucket markets)
  bucket_signal.py          range-bucket probability math, wired in via tc_temp_parser.py
  position_sizing.py        Kelly-criterion position sizing
  risk_manager.py           pause/kill-switch + position/session/daily caps
  us_client.py              polymarket-us SDK wrapper, rate-limited
  trader.py                 executes signals (dry-run or live) + Telegram alert
  telegram_bot.py           minimal Telegram Bot API client (plain HTTPS)
  telegram_commands.py      background thread handling /status /pause /resume /report
  dashboard_state.py        thread-safe shared state written by bot.py, read by dashboard.py
  dashboard.py              FastAPI app + background thread serving the real-time dashboard
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
| `STORM_DASHBOARD_ENABLED` | `true` (default) serves the real-time dashboard; `false` disables it. Never affects trading either way. |
| `PORT` | Port the dashboard listens on. Railway injects this automatically for the public service; only set it yourself for local runs (defaults to `8000`). |

## Deploying to Railway

This repo runs as a Railway **web** service — `python main.py` both runs
the scan/trade loop and serves the dashboard on `PORT`:

- `Procfile` / `railway.json` run `python main.py` on start, restarting on
  failure. `railway.json` also points Railway's health check at
  `GET /healthz`.
- Set all variables from `.env.example` as Railway project variables
  (never commit a real `.env`). Leave `PORT` unset — Railway provides it.
- Enable **Public Networking** on the service (Railway settings) if you
  want the dashboard reachable at a public URL; the scan/trade loop runs
  identically either way.
- Deploy with `LIVE_TRADING=false` first, watch the logs/Telegram/
  dashboard for a few cycles of dry-run output, then flip
  `LIVE_TRADING=true` once you're satisfied.
- `RAILWAY_DEPLOYMENT_OVERLAP_SECONDS` (visible on Colossus's Railway
  service) is a Railway platform setting, not something Storm's code
  reads — set it directly in Railway's service settings if you want to
  control the zero-downtime deploy overlap window.

## Testing

```bash
pytest
```

All tests are pure unit tests (rate limiter timing, risk manager caps/
persistence, market filter/parser, tc-temp slug parsing, bucket
probability math, signal engine, Telegram command handling, dashboard
state/API) — no network calls, so they run the same locally and in CI.
