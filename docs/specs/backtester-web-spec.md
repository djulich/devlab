# Stock Trading Strategy Backtester — Web Application

## Purpose

A web application providing the same backtesting features as the desktop backtester: single-run backtests and entry-time sweep analysis for stock trading strategies, with interactive charts and detailed trade logs. The web interface allows multiple users to run backtests concurrently from any browser without installing Python or dependencies locally.

The same design principle applies: adding a new trading strategy requires implementing a single Python class — no changes to the API, frontend, or engine.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                Browser (React + Plotly.js)                │
│  strategy selection, parameters, charts, trade table      │
└──────────────────┬───────────────────────────────────────┘
                   │  REST + WebSocket
┌──────────────────▼───────────────────────────────────────┐
│              API Server (FastAPI)                         │
│  /api/strategies, /api/backtest, /api/sweep              │
│  WebSocket: sweep progress                               │
└──────┬───────────────────────┬───────────────────────────┘
       │                       │
┌──────▼──────┐    ┌───────────▼──────────────┐
│ Data Layer  │    │    Strategy + Engine     │
│ (yfinance)  │    │  (shared Python core)    │
└─────────────┘    └──────────────────────────┘
```

The project has two build targets:

| Component | Technology | Build |
|-----------|-----------|-------|
| Backend | Python 3.12+, FastAPI, uvicorn | uv |
| Frontend | TypeScript, React, Vite | npm |

The backend reuses the same core libraries as the desktop backtester: data layer (yfinance), strategy interface, backtesting engine, sweep runner, indicators, and persistence logic. The API server is a thin layer that exposes these capabilities over HTTP and WebSocket.

The frontend is a single-page application that communicates with the backend API. In production, a reverse proxy (nginx) serves the built frontend static files and proxies API requests to the backend.

## Shared Python Core

The backtesting core — data layer, strategy interface, engine, sweep runner, indicators — is identical in behaviour to the desktop backtester spec. This section summarises the shared components; see the desktop backtester spec for full details.

### Data layer

- yfinance `Ticker.history()` for OHLCV data.
- Daily (`1d`, 20-year lookback) and hourly (`1h`, 730-day lookback) resolutions.
- In-memory cache with subset slicing. Cache is per-process (not shared across workers).
- Validation: unknown symbols, lookback limits, date ordering, gap detection.

### Strategy interface

Same `Strategy` base class with `config()`, `__init__(**params)`, `on_bar(history)`, and `reset()`. Same `Signal` enum (`BUY`, `SELL`, `HOLD`). Same `StrategyConfig` for parameter metadata.

### Bundled strategies

Same five strategies: SMA Crossover, RSI Mean Reversion, MACD Crossover, Bollinger Band Breakout, Buy and Hold. All indicators computed from scratch in pandas.

### Engine

Same bar-by-bar execution model, portfolio state, trade log, and result metrics (total return, annualised return, max drawdown, Sharpe ratio, Sortino ratio, trade count, win rate, profit factor, average trade duration).

### Sweep

Same entry-time sweep: configurable holding period, entry step, family of normalised equity curves, aggregate statistics (probability of profit, median/mean/worst/best return, percentiles).

## API Server

FastAPI application served by uvicorn. All endpoints are under `/api/`.

### Endpoints

**`GET /api/strategies`**

Returns the list of available strategies with their parameter metadata.

```json
[
  {
    "name": "SMA Crossover",
    "description": "Buy when short SMA crosses above long SMA...",
    "parameters": {
      "short_window": {"type": "int", "default": 20},
      "long_window": {"type": "int", "default": 50}
    }
  },
  ...
]
```

**`POST /api/backtest`**

Runs a single backtest synchronously and returns the full result.

Request body:
```json
{
  "symbol": "AAPL",
  "strategy": "SMA Crossover",
  "parameters": {"short_window": 20, "long_window": 50},
  "interval": "1d",
  "start_date": "2023-01-01",
  "end_date": "2025-01-01",
  "initial_cash": 10000
}
```

Response body:
```json
{
  "portfolio_values": [[<timestamp_ms>, <value>], ...],
  "price_series": [[<timestamp_ms>, <price>], ...],
  "trades": [
    {
      "entry_date": "2023-02-15",
      "exit_date": "2023-04-03",
      "entry_price": 152.30,
      "exit_price": 165.10,
      "shares": 45,
      "pnl": 576.00,
      "return_pct": 8.4,
      "duration_bars": 33
    },
    ...
  ],
  "metrics": {
    "total_return_pct": 23.4,
    "annualised_return_pct": 11.2,
    "max_drawdown_pct": -8.7,
    "sharpe_ratio": 1.34,
    "sortino_ratio": 1.87,
    "num_trades": 12,
    "win_rate_pct": 66.7,
    "profit_factor": 2.1,
    "avg_trade_duration_bars": 18
  },
  "meta": {
    "symbol": "AAPL",
    "strategy": "SMA Crossover",
    "parameters": {"short_window": 20, "long_window": 50},
    "interval": "1d",
    "start_date": "2023-01-01",
    "end_date": "2025-01-01",
    "initial_cash": 10000,
    "total_bars": 503,
    "gap_count": 0
  }
}
```

Timestamps in `portfolio_values` and `price_series` are Unix milliseconds (for direct use by Plotly.js).

**`POST /api/sweep`**

Initiates an entry-time sweep. Because sweeps involve many individual backtests and can take significant time, this endpoint returns a sweep ID immediately. Progress and results are delivered via WebSocket.

Request body:
```json
{
  "symbol": "AAPL",
  "strategy": "SMA Crossover",
  "parameters": {"short_window": 20, "long_window": 50},
  "interval": "1d",
  "start_date": "2020-01-01",
  "end_date": "2025-12-31",
  "initial_cash": 10000,
  "holding_period_days": 252,
  "entry_step_days": 20
}
```

Response:
```json
{
  "sweep_id": "sw_abc123"
}
```

**`WebSocket /api/sweep/{sweep_id}/ws`**

Streams progress and results for a sweep.

Progress message (sent after each entry-date backtest completes):
```json
{
  "type": "progress",
  "completed": 15,
  "total": 48
}
```

Result message (sent once when the sweep finishes):
```json
{
  "type": "result",
  "curves": [
    {
      "entry_date": "2020-01-02",
      "values": [1.0, 1.002, 1.015, ...],
      "final_return_pct": 14.2
    },
    ...
  ],
  "statistics": {
    "count": 48,
    "median_return_pct": 14.2,
    "mean_return_pct": 16.8,
    "worst_return_pct": -12.3,
    "best_return_pct": 45.1,
    "profit_probability_pct": 72.9,
    "percentiles": {
      "p10": -3.1,
      "p25": 5.4,
      "p75": 24.7,
      "p90": 38.2
    }
  }
}
```

**`GET /api/health`**

Returns `{"status": "ok"}`. Used by deployment smoke tests and load balancer health checks.

### Error handling

All endpoints return structured error responses:

```json
{
  "error": "invalid_symbol",
  "message": "No data found for symbol 'INVALID'. Verify the ticker symbol."
}
```

Error codes: `invalid_symbol`, `invalid_date_range`, `invalid_interval`, `unknown_strategy`, `invalid_parameters`, `data_fetch_error`, `sweep_not_found`.

HTTP status codes: 400 for validation errors, 404 for unknown sweep IDs, 502 for upstream yfinance failures, 500 for unexpected errors.

### Concurrency

The API server runs sweep backtests in a background thread pool (via `asyncio.to_thread`) to avoid blocking the event loop. Single backtests are fast enough to run synchronously in the request handler.

Active sweeps are stored in an in-memory dict keyed by sweep ID. Sweep results are retained for 1 hour after completion, then evicted. There is no persistent job queue — if the server restarts, in-progress sweeps are lost.

## Frontend

Single-page React application built with Vite and TypeScript.

### Dependencies

| Library | Purpose |
|---------|---------|
| React 19 | UI framework |
| Plotly.js (react-plotly.js) | Interactive charts |
| TypeScript | Type safety |
| Vite | Build tool and dev server |

No CSS framework. Use plain CSS with CSS modules or a single stylesheet. The UI should be functional, not polished — default browser styling with sensible spacing and layout is sufficient.

### Pages

The application has a single page with two areas: a control panel and a results area.

### Control Panel

Same fields as the desktop backtester:

- Symbol text input.
- Strategy dropdown (populated from `GET /api/strategies`).
- Resolution radio buttons: Daily / Hourly.
- Start date and end date inputs (type `date`).
- Strategy parameters: dynamically rendered based on the selected strategy's parameter metadata. Each parameter gets a labelled numeric input with its default value pre-filled.
- Initial cash numeric input (default 10000).
- "Run Backtest" button — calls `POST /api/backtest`.
- "Run Entry Sweep" button — calls `POST /api/sweep`, then connects to the WebSocket.
- Sweep settings (visible when relevant): holding period dropdown (6 months, 1 year, 2 years), entry step numeric input (trading days, default 20).

Both buttons are disabled while a run is in progress. The sweep button shows a progress bar updated via WebSocket messages.

### Results Area

Uses a tab layout matching the desktop backtester.

**Tab: Single Backtest**

Shown after a backtest completes.

Portfolio Value chart (Plotly.js):
- X-axis: date. Y-axis: dollar value.
- Strategy portfolio value as a solid line.
- Buy-and-hold baseline normalised to the same initial cash.
- Buy trades as green triangle-up markers, sell trades as red triangle-down markers.
- Interactive: zoom, pan, hover tooltips showing date and value.

Price chart (Plotly.js):
- X-axis: date (shared with portfolio chart via Plotly `subplots` with shared x-axis). Y-axis: price.
- Close price line with buy/sell markers at execution prices.

Summary panel:
- All nine metrics displayed in a grid layout.

Trade log table:
- Scrollable HTML table with columns: #, Entry Date, Exit Date, Entry Price, Exit Price, Shares, P&L, Return (%), Duration (bars).
- Rows coloured: green background for profitable trades, red for losing trades.

**Tab: Entry Sweep**

Shown after a sweep completes.

Equity Curves chart (Plotly.js):
- X-axis: trading days since entry (0 = entry date). Y-axis: normalised portfolio value (1.0 = start).
- Each curve as a thin semi-transparent line, coloured green-to-red by final return.
- Shaded band for 25th–75th percentile envelope.
- Dashed line for the median curve.
- Horizontal line at 1.0 (breakeven).
- Interactive: hover shows entry date and current normalised value.

Return Distribution chart (Plotly.js):
- Histogram of final returns across all entry dates.
- Vertical dashed line at 0% (breakeven).
- Vertical solid line at median return, labelled.

Sweep Summary panel:
- Count, probability of profit, median/mean/worst/best return, percentiles — same layout as desktop.

### Export

- Each Plotly chart has a built-in toolbar with PNG/SVG export (Plotly's default `modeBar`).
- A "Download Trade Log CSV" button below the trade table calls a utility function that generates and triggers a browser download of the CSV.
- A "Download Sweep CSV" button below the sweep summary does the same for per-entry-date returns.

These exports are client-side only (no additional API endpoints).

### API Communication

- Use the browser `fetch` API for REST calls. No axios or other HTTP library.
- Use the browser `WebSocket` API for sweep progress. No socket.io.
- API base URL is configured via a Vite environment variable `VITE_API_URL`, defaulting to `/api` (for production behind a reverse proxy) or `http://localhost:8000/api` during development.

### Error Display

- Validation errors from the API are displayed in a dismissible alert banner above the results area.
- Network errors show a generic "Could not reach the server" message.
- WebSocket disconnection during a sweep shows "Connection lost — sweep results may be incomplete".

## Project Structure

```
backtester-web/
├── pyproject.toml
├── Makefile
├── backend/
│   ├── src/
│   │   └── backtester/
│   │       ├── __init__.py
│   │       ├── data.py
│   │       ├── engine.py
│   │       ├── sweep.py
│   │       ├── indicators.py
│   │       ├── strategy/
│   │       │   ├── __init__.py
│   │       │   ├── sma_crossover.py
│   │       │   ├── rsi_reversion.py
│   │       │   ├── macd_crossover.py
│   │       │   ├── bollinger_breakout.py
│   │       │   └── buy_and_hold.py
│   │       └── api/
│   │           ├── __init__.py
│   │           ├── app.py           # FastAPI app, lifespan, CORS
│   │           ├── routes.py        # endpoint handlers
│   │           ├── schemas.py       # Pydantic request/response models
│   │           └── sweep_manager.py # background sweep tracking
│   └── tests/
│       ├── test_data.py
│       ├── test_engine.py
│       ├── test_sweep.py
│       ├── test_indicators.py
│       ├── test_strategies.py
│       ├── test_routes.py           # FastAPI TestClient integration tests
│       └── test_sweep_manager.py
├── frontend/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api.ts                   # fetch + WebSocket helpers
│       ├── types.ts                 # TypeScript types matching API schemas
│       ├── components/
│       │   ├── ControlPanel.tsx
│       │   ├── StrategyParams.tsx   # dynamic parameter fields
│       │   ├── BacktestTab.tsx
│       │   ├── SweepTab.tsx
│       │   ├── PortfolioChart.tsx
│       │   ├── PriceChart.tsx
│       │   ├── EquityCurves.tsx
│       │   ├── ReturnHistogram.tsx
│       │   ├── TradeTable.tsx
│       │   ├── MetricsSummary.tsx
│       │   ├── SweepSummary.tsx
│       │   ├── ProgressBar.tsx
│       │   └── ErrorBanner.tsx
│       └── styles/
│           └── app.css
└── nginx/
    └── default.conf                 # reverse proxy config
```

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Backend language | Python 3.12+ |
| API framework | FastAPI |
| ASGI server | uvicorn |
| Market data | yfinance |
| Data manipulation | pandas |
| Backend tests | pytest, httpx (for FastAPI TestClient) |
| Frontend language | TypeScript |
| Frontend framework | React 19 |
| Charts | Plotly.js (react-plotly.js) |
| Build tool | Vite |
| Package managers | uv (backend), npm (frontend) |
| Reverse proxy | nginx (production) |

## Development Workflow

### Backend

```bash
cd backend
uv sync
uv run uvicorn backtester.api.app:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
VITE_API_URL=http://localhost:8000/api npm run dev
```

Vite dev server runs on port 5173 with hot reload. API requests proxy to the backend at port 8000.

### Full stack (development)

```bash
make dev
```

Starts both backend and frontend dev servers concurrently.

## Entry Point

Development: `make dev` (starts both servers).
Production: the application runs as a Docker Compose stack or Kubernetes deployment — see the deployment spec.
