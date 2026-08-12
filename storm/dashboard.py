"""Read-only, real-time dashboard onto DashboardState.

Purely additive per explicit user request: it never touches the trading
loop, only serves what storm/bot.py already records into DashboardState
every cycle. Runs on its own daemon thread (uvicorn) alongside the main
synchronous scan loop, the same pattern storm/telegram_commands.py uses
for the Telegram listener, since Storm's main loop isn't asyncio-based.

Two surfaces:
- GET /api/state - JSON snapshot (weather/markets/history/scan summary
  for the three tracked airports), for any external consumer.
- GET / - a single auto-refreshing HTML page that polls /api/state.
"""

from __future__ import annotations

import logging
import threading

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from storm.airports import AIRPORTS
from storm.dashboard_state import DashboardState

logger = logging.getLogger(__name__)

_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Storm Weather Dashboard</title>
<style>
  body { font-family: -apple-system, Helvetica, Arial, sans-serif; background: #0b1220; color: #e6edf3; margin: 0; padding: 24px; }
  h1 { margin: 0 0 4px; font-size: 22px; }
  .sub { color: #8b949e; font-size: 13px; margin-bottom: 20px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
  .card h2 { margin: 0 0 10px; font-size: 16px; }
  .row { display: flex; justify-content: space-between; font-size: 13px; padding: 4px 0; border-bottom: 1px solid #21262d; }
  .row:last-child { border-bottom: none; }
  .yes { color: #3fb950; font-weight: 600; }
  .no { color: #f85149; font-weight: 600; }
  .muted { color: #8b949e; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #21262d; }
  th { color: #8b949e; font-weight: 500; }
  #status { font-size: 12px; color: #8b949e; }
</style>
</head>
<body>
  <h1>Storm Weather Dashboard</h1>
  <div class="sub">MIA &middot; ORD &middot; LAX &mdash; <span id="status">loading&hellip;</span></div>
  <div class="grid" id="airport-cards"></div>
  <div class="card" style="margin-top:16px">
    <h2>Recent Signals</h2>
    <table id="history-table"><thead><tr><th>Time</th><th>Airport</th><th>Market</th><th>Side</th><th>Edge</th></tr></thead><tbody></tbody></table>
  </div>

<script>
const AIRPORTS = ["mia", "ord", "lax"];
const NAMES = { mia: "Miami (MIA)", ord: "Chicago O'Hare (ORD)", lax: "Los Angeles (LAX)" };

function fmtPct(x) { return x === null || x === undefined ? "-" : (x * 100).toFixed(1) + "%"; }
function fmtNum(x, d) { return x === null || x === undefined ? "-" : Number(x).toFixed(d === undefined ? 1 : d); }
function sideClass(side) { return side === "YES" ? "yes" : side === "NO" ? "no" : "muted"; }

function renderAirportCard(code, weather, markets) {
  let html = `<div class="card"><h2>${NAMES[code]}</h2>`;
  if (weather) {
    html += `<div class="row"><span>Blended forecast</span><span>${fmtNum(weather.blended_forecast)}&deg;F</span></div>`;
    html += `<div class="row"><span>NWS</span><span>${fmtNum(weather.nws_forecast)}&deg;F</span></div>`;
    html += `<div class="row"><span>Open-Meteo</span><span>${fmtNum(weather.open_meteo_forecast)}&deg;F</span></div>`;
  } else {
    html += `<div class="row muted"><span>No forecast recorded yet</span></div>`;
  }
  const entries = Object.entries(markets || {}).sort((a, b) => (b[1].updated_at || "").localeCompare(a[1].updated_at || ""));
  if (entries.length === 0) {
    html += `<div class="row muted"><span>No markets scanned yet</span></div>`;
  } else {
    for (const [slug, m] of entries.slice(0, 8)) {
      html += `<div class="row"><span title="${slug}">${slug.length > 28 ? slug.slice(0, 28) + '…' : slug}</span>` +
        `<span class="${sideClass(m.side)}">${m.side || 'no edge'} ${m.edge !== null && m.edge !== undefined ? '(' + fmtPct(m.edge) + ')' : ''}</span></div>`;
    }
  }
  html += `</div>`;
  return html;
}

async function refresh() {
  try {
    const res = await fetch("/api/state");
    const state = await res.json();
    document.getElementById("status").textContent =
      state.last_scan_at ? `last scan ${state.last_scan_at} — ${state.last_scan_summary.total_markets || 0} markets, ${state.last_scan_summary.weather_related || 0} weather-related` : "waiting for first scan…";

    document.getElementById("airport-cards").innerHTML = AIRPORTS
      .map(code => renderAirportCard(code, state.weather[code], state.markets[code]))
      .join("");

    const tbody = document.querySelector("#history-table tbody");
    tbody.innerHTML = (state.history || []).slice(0, 25).map(h =>
      `<tr><td>${(h.recorded_at || "").replace("T", " ").slice(0, 19)}</td><td>${(h.airport || "").toUpperCase()}</td>` +
      `<td title="${h.question || ''}">${h.market_slug || ''}</td><td class="${sideClass(h.side)}">${h.side || ''}</td><td>${fmtPct(h.edge)}</td></tr>`
    ).join("") || `<tr><td colspan="5" class="muted">No signals yet</td></tr>`;
  } catch (err) {
    document.getElementById("status").textContent = "dashboard fetch failed - retrying…";
  }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


def build_app(dashboard_state: DashboardState) -> FastAPI:
    app = FastAPI(title="Storm Weather Dashboard")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _PAGE

    @app.get("/api/state")
    def api_state() -> dict:
        snapshot = dashboard_state.snapshot()
        snapshot["airports"] = {
            code: {"name": airport.name, "lat": airport.lat, "lon": airport.lon} for code, airport in AIRPORTS.items()
        }
        return snapshot

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app


class DashboardServer(threading.Thread):
    """Runs the dashboard's FastAPI app via uvicorn on a daemon thread, so
    it exits automatically with the main process rather than needing its
    own shutdown handshake."""

    def __init__(self, dashboard_state: DashboardState, host: str = "0.0.0.0", port: int = 8000):
        super().__init__(daemon=True, name="storm-dashboard")
        self._config = uvicorn.Config(
            build_app(dashboard_state), host=host, port=port, log_level="warning", access_log=False
        )
        self._server = uvicorn.Server(self._config)

    def run(self) -> None:
        logger.info("Starting Storm dashboard on %s:%d", self._config.host, self._config.port)
        try:
            self._server.run()
        except Exception:
            logger.exception("Storm dashboard server crashed")
