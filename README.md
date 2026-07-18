# Storm

Storm is a Polymarket trading bot focused exclusively on weather markets
(temperature, rain, snow, storms, etc). It is a companion to **Colossus**,
a separate bot that trades most sports-league markets — different repo,
different Railway project, but the **same Polymarket account/API key**.

## How it works

Every cycle (`STORM_POLL_INTERVAL_SECONDS`, default 300s), Storm:

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
6. **Trades (or logs)** — the risk manager checks the kill switch and
   position/daily caps, then the trader either logs a dry-run line or
   places a real order via `py-clob-client` (`storm/risk_manager.py`,
   `storm/trader.py`, `storm/clob_client.py`).

The market-question parser is intentionally conservative: it returns `None`
(skip) rather than guess when it doesn't recognize the phrasing. Extend
`CITY_COORDINATES` and the keyword lists in `storm/market_parser.py` /
`storm/market_filter.py` as you find weather markets Storm misses.

## Sharing a Polymarket account with Colossus

Storm and Colossus use the same Polymarket API key/account but are
otherwise fully independent (separate repos, separate Railway projects,
separate processes). Two things keep them from interfering with each
other:

- **Market scope**: `storm/market_filter.py`'s keyword filter is what keeps
  Storm out of Colossus's sports markets, and vice versa. There's no
  shared registry — if you see overlap, tighten the keyword lists.
- **Rate limiting**: `storm/rate_limiter.py` is a token-bucket limiter
  applied to *every* Polymarket call Storm makes (Gamma reads and CLOB
  order calls alike — see `main.py`'s single shared `TokenBucketRateLimiter`
  instance). It only throttles Storm's own traffic; it does not coordinate
  with Colossus's process. Keep `STORM_MAX_REQUESTS_PER_SECOND` set to a
  conservative fraction of the account's overall documented rate limit so
  Storm's usage plus Colossus's stays under the ceiling. If both bots'
  request volume grows, consider a shared external limiter (e.g. Redis)
  instead of two independent self-throttles.

## Trading safety

Storm ships defensively since it can trade with real funds on a
shared account:

- **Dry-run by default.** `LIVE_TRADING` defaults to `false` — Storm scans
  markets and logs exactly what it *would* trade without sending any
  orders. Set `LIVE_TRADING=true` (e.g. as a Railway variable) once you've
  verified its behavior.
- **Kill switch, two ways**: set `STORM_KILL_SWITCH=true` (env var, needs a
  redeploy/restart) or create the file named by `STORM_KILL_SWITCH_FILE`
  (default `storm.kill`) on disk — Storm checks it every cycle with no
  restart required. Either one stops Storm from opening new trades;
  existing positions are left alone.
- **Hard caps**: `STORM_MAX_POSITION_USDC` caps every individual trade;
  `STORM_MAX_DAILY_SPEND_USDC` caps total spend per UTC day. Both are
  enforced in `storm/risk_manager.py` regardless of how confident a signal
  is.

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
  risk_manager.py           kill switch + position/daily caps
  clob_client.py            py-clob-client wrapper, rate-limited
  trader.py                 executes signals (dry-run or live)
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
| `POLYMARKET_PRIVATE_KEY`, `POLYMARKET_FUNDER_ADDRESS` | Wallet used to sign/fund orders (same account as Colossus). Required only when `LIVE_TRADING=true`. |
| `POLYMARKET_API_KEY/SECRET/PASSPHRASE` | Optional L2 API creds; if left blank, Storm derives them from the private key at startup. |
| `LIVE_TRADING` | `false` (default) = dry-run/log only. `true` = place real orders. |
| `STORM_KILL_SWITCH`, `STORM_KILL_SWITCH_FILE` | Stop opening new trades (env var or file-based). |
| `STORM_MAX_POSITION_USDC`, `STORM_MAX_DAILY_SPEND_USDC` | Hard trading caps. |
| `STORM_MIN_EDGE` | Minimum estimated-probability vs. market-price gap required to trade. |
| `STORM_MAX_REQUESTS_PER_SECOND`, `STORM_RATE_LIMITER_BURST` | Storm's self-throttle share of the shared Polymarket account's rate limit. |
| `NWS_USER_AGENT` | Required by NWS's usage policy — set to something identifying (e.g. an email). |

## Deploying to Railway

This repo is set up for a Railway **worker** service (no HTTP port needed):

- `Procfile` / `railway.json` run `python main.py` on start, restarting on
  failure.
- Set all variables from `.env.example` as Railway project variables
  (never commit a real `.env`).
- Deploy with `LIVE_TRADING=false` first, watch the logs for a few cycles
  of dry-run output, then flip `LIVE_TRADING=true` once you're satisfied.

## Testing

```bash
pytest
```

All tests are pure unit tests (rate limiter timing, risk manager caps,
market filter/parser, signal engine) — no network calls, so they run the
same locally and in CI.
