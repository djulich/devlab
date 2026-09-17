# Stock Trading Strategy Backtester

## Purpose

A desktop application for backtesting stock trading strategies against historical market data. Users select a trading algorithm, a stock symbol, a time window, and a data resolution, then run the backtest and view performance results as interactive graphs and summary statistics.

The application prioritises extensibility of trading strategies: adding a new strategy requires implementing a single Python class with a well-defined interface — no changes to the backtesting engine, GUI, or data layer.

## Architecture

```
┌─────────────────────────────────────────────┐
│                   GUI (tkinter)             │
│  symbol, strategy, resolution, date range   │
│  result graphs (matplotlib) + summary text  │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│             Backtesting Engine              │
│  iterates price bars, calls strategy,       │
│  tracks portfolio state, computes metrics   │
│  single-run and entry-sweep modes           │
└──────┬───────────────────────┬──────────────┘
       │                       │
┌──────▼──────┐    ┌───────────▼──────────────┐
│ Data Layer  │    │    Strategy Interface     │
│ (yfinance)  │    │  + bundled strategies     │
└─────────────┘    └──────────────────────────┘
```

Four top-level packages:

| Package | Responsibility |
|---------|----------------|
| `data` | Fetch and cache historical OHLCV data via yfinance. |
| `strategy` | Strategy base class, registry, and bundled implementations. |
| `engine` | Bar-by-bar backtest loop, portfolio tracking, metric computation, entry-sweep analysis. |
| `gui` | tkinter main window, parameter inputs, matplotlib result display, tabbed result views. |

## Data Layer

Use the yfinance `Ticker.history()` API to download OHLCV (Open, High, Low, Close, Volume) data.

### Supported resolutions

| Label | yfinance interval | Max lookback |
|-------|-------------------|--------------|
| Daily | `1d` | up to 20 years |
| Hourly | `1h` | last 730 days |

The data layer accepts a symbol string, a start date, an end date, and an interval. It returns a pandas DataFrame indexed by datetime with columns: `Open`, `High`, `Low`, `Close`, `Volume`.

Dividends and splits columns are dropped; `auto_adjust=True` (default) is used so prices are split- and dividend-adjusted.

### Validation

- Reject unknown symbols (yfinance returns an empty DataFrame).
- Reject date ranges that exceed the interval's lookback limit.
- Reject date ranges where the start is after the end.
- Warn when the returned data has gaps (e.g. missing hourly bars on holidays or outside trading hours) and report the gap count in the result metadata.

### Caching

Cache downloaded data in memory for the lifetime of the application so repeated backtests on the same symbol/interval/range do not re-fetch. The cache key is `(symbol, interval, start, end)`. When a request's date range is a subset of a cached range, slice the cached DataFrame instead of re-fetching.

## Strategy Interface

All strategies implement a base class:

```python
from dataclasses import dataclass
from enum import Enum
import pandas as pd


class Signal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class StrategyConfig:
    """User-visible parameter metadata for GUI rendering."""
    name: str
    description: str
    parameters: dict[str, tuple[type, object]]
    # key -> (type, default_value)
    # supported types: int, float


class Strategy:
    """Base class for all trading strategies."""

    @staticmethod
    def config() -> StrategyConfig:
        """Return metadata and default parameters for this strategy."""
        raise NotImplementedError

    def __init__(self, **params: object) -> None:
        """Initialise with user-supplied parameter values."""
        ...

    def on_bar(self, history: pd.DataFrame) -> Signal:
        """Receive all bars up to and including the current bar.

        ``history`` is a DataFrame of OHLCV data from the backtest start
        up to and including the current bar (inclusive slice).  The
        strategy returns a Signal for the current bar.
        """
        raise NotImplementedError

    def reset(self) -> None:
        """Reset internal state for a fresh backtest run."""
        ...
```

### Strategy registry

Strategies register via a module-level list in `strategy/__init__.py`. To add a strategy the user creates a new module in the `strategy/` package, implements the `Strategy` base class, and adds an import to the registry list. No other files need to change.

### Bundled strategies

Ship with these five strategies so the GUI is immediately useful and the entry-sweep analysis produces interesting comparisons:

1. **SMA Crossover** — buy when a short simple moving average crosses above a long SMA; sell on the reverse crossover. Parameters: `short_window` (int, default 20), `long_window` (int, default 50).

2. **RSI Mean Reversion** — buy when RSI drops below an oversold threshold; sell when it rises above an overbought threshold. Parameters: `rsi_period` (int, default 14), `oversold` (float, default 30.0), `overbought` (float, default 70.0).

3. **MACD Crossover** — buy when the MACD line crosses above the signal line; sell on the reverse crossover. Parameters: `fast_period` (int, default 12), `slow_period` (int, default 26), `signal_period` (int, default 9).

4. **Bollinger Band Breakout** — buy when the close price crosses above the upper Bollinger Band; sell when it crosses below the lower band. Parameters: `bb_period` (int, default 20), `num_std` (float, default 2.0).

5. **Buy and Hold** — buy on the first bar, hold until the end. No parameters. Serves as the baseline benchmark.

All indicator calculations (SMA, EMA, RSI, MACD, Bollinger Bands) are implemented from scratch using pandas operations — no dependency on TA-Lib or similar external indicator libraries.

## Backtesting Engine

### Execution model

The engine iterates over the price DataFrame bar by bar in chronological order. For each bar it:

1. Calls `strategy.on_bar(history_up_to_current_bar)` to get a signal.
2. Executes the signal against the portfolio:
   - **BUY**: if not already holding, buy as many whole shares as the available cash allows at the bar's `Close` price.
   - **SELL**: if holding, sell all shares at the bar's `Close` price.
   - **HOLD**: do nothing.
3. Records the portfolio value (cash + shares * close price) for the bar.

### Portfolio state

- Start with a configurable initial cash amount (default: $10,000).
- Track: cash balance, shares held, list of executed trades (date, action, price, shares, value).
- No short selling. No fractional shares. No commission fees in the initial version.

### Result metrics

After the backtest completes, compute:

| Metric | Definition |
|--------|------------|
| Total return (%) | `(final_value - initial_cash) / initial_cash * 100` |
| Annualised return (%) | Total return scaled to a 252-trading-day year. |
| Max drawdown (%) | Largest peak-to-trough decline in portfolio value. |
| Sharpe ratio | Annualised ratio of mean excess return to return standard deviation (risk-free rate = 0). |
| Sortino ratio | Like Sharpe but uses only downside deviation (negative returns) in the denominator. |
| Number of trades | Count of executed buy+sell round trips. |
| Win rate (%) | Percentage of round-trip trades that were profitable. |
| Profit factor | Gross profit divided by gross loss across all round-trip trades. Infinity if no losing trades. |
| Average trade duration | Mean number of bars between buy and corresponding sell. |

### Trade log

Each trade record contains: entry date, exit date, entry price, exit price, shares, dollar P&L, percentage return, and duration in bars. The trade log is displayed in the GUI and is the basis for win rate, profit factor, and average duration calculations.

### Result data

Return a dataclass containing:

- The portfolio value series (DatetimeIndex → float).
- The price series for the symbol (for overlay plotting).
- The trade log (list of trade records).
- The computed metrics dict.
- The strategy name and parameters used.
- The symbol, interval, and date range.
- Data quality metadata: total bars, gap count.

## Entry-Time Sweep Analysis

### Concept

A single backtest starting on a specific date can be misleading — the outcome depends heavily on whether the entry happened to coincide with a favourable or unfavourable market phase. The entry-time sweep runs the same strategy across many different entry dates within a given data window, producing a family of equity curves that shows how sensitive the strategy's performance is to entry timing.

### How it works

The user specifies:

- A **data window** covering the full date range of available data (e.g. 2020-01-01 to 2025-12-31).
- A **holding period** — the duration of each individual backtest (e.g. 1 year, 6 months, 2 years).
- An **entry step** — how far apart the entry dates are spaced (e.g. every 5 trading days, every 20 trading days).

The engine generates a series of entry dates starting from the beginning of the data window, spaced by the entry step. For each entry date, it runs a full backtest from that date forward for the holding period duration. Each run uses a fresh strategy instance (via `reset()`), the same initial cash, and the same parameters.

Entry dates where the data window does not contain enough bars to cover the full holding period are skipped.

### Sweep result data

The sweep produces:

- A collection of equity curves, one per entry date, each normalised to start at 1.0 (so they can be overlaid regardless of entry price).
- Per-curve final return (%).
- Aggregate statistics across all curves:

| Statistic | Definition |
|-----------|------------|
| Median final return (%) | Median of all individual run returns. |
| Mean final return (%) | Mean of all individual run returns. |
| Worst-case return (%) | Minimum final return across all runs. |
| Best-case return (%) | Maximum final return across all runs. |
| Probability of profit (%) | Percentage of runs that ended with a positive return. |
| Return percentiles | 10th, 25th, 75th, and 90th percentile final returns. |

## GUI

Build with tkinter (stdlib). Embed matplotlib figures via `matplotlib.backends.backend_tkagg`.

### Layout

The window has two areas: a control panel at the top and a tabbed result area below.

#### Control panel

```
┌──────────────────────────────────────────────────────────────┐
│  Stock Trading Strategy Backtester                           │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Symbol: [________]   Strategy: [▼ SMA Crossover      ]     │
│                                                              │
│  Resolution: (•) Daily  ( ) Hourly                           │
│                                                              │
│  Start date: [YYYY-MM-DD]   End date: [YYYY-MM-DD]          │
│                                                              │
│  Strategy parameters:                                        │
│    short_window: [20]   long_window: [50]                    │
│                                                              │
│  Initial cash: [10000]                                       │
│                                                              │
│  [ Run Backtest ]   [ Run Entry Sweep ]                      │
│                                                              │
│  Entry sweep settings (shown when sweep mode selected):      │
│    Holding period: [1y ▼]   Entry step: [20] trading days    │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

#### Result tabs

Results are displayed in a notebook (tabbed) widget with tabs appearing after a backtest or sweep completes.

**Tab: Single Backtest**

Shown after "Run Backtest":

```
┌─ Single Backtest ─────────────────────────────────────────────┐
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ Portfolio Value Over Time                               │  │
│  │  — Portfolio value                                      │  │
│  │  — Buy & hold baseline (normalised to same start)       │  │
│  │  ▲ Buy markers   ▼ Sell markers                         │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ Price Chart                                             │  │
│  │  — Close price   ▲ Buy markers   ▼ Sell markers         │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                               │
│  Summary:                                                     │
│  Total return: +23.4%    Annualised: +11.2%                   │
│  Max drawdown: -8.7%     Sharpe: 1.34    Sortino: 1.87        │
│  Trades: 12   Win rate: 66.7%   Profit factor: 2.1            │
│  Avg trade duration: 18 bars                                  │
│                                                               │
│  Trade Log:                                                   │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ # │ Entry      │ Exit       │ Shares │ P&L    │ Return │  │
│  │ 1 │ 2023-02-15 │ 2023-04-03 │ 45     │ +$312  │ +3.1%  │  │
│  │ 2 │ 2023-05-10 │ 2023-05-28 │ 42     │ -$89   │ -0.9%  │  │
│  │ ...                                                     │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

**Tab: Entry Sweep**

Shown after "Run Entry Sweep":

```
┌─ Entry Sweep ─────────────────────────────────────────────────┐
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ Equity Curves by Entry Date                             │  │
│  │                                                         │  │
│  │  Each line = one backtest starting at a different date   │  │
│  │  X-axis: trading days since entry (0 = entry date)       │  │
│  │  Y-axis: normalised portfolio value (1.0 = start)        │  │
│  │  Lines coloured by final return (green=profit, red=loss) │  │
│  │  Shaded band: 25th–75th percentile envelope              │  │
│  │  Dashed line: median curve                               │  │
│  │  Horizontal line at 1.0 (breakeven)                      │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ Return Distribution                                     │  │
│  │                                                         │  │
│  │  Histogram of final returns across all entry dates       │  │
│  │  Vertical line at 0% (breakeven)                         │  │
│  │  Vertical line at median return                          │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                               │
│  Sweep Summary (N = 48 entry dates):                          │
│  Probability of profit: 72.9%                                 │
│  Median return: +14.2%     Mean return: +16.8%                │
│  Worst case: -12.3%        Best case: +45.1%                  │
│  10th pct: -3.1%   25th pct: +5.4%                            │
│  75th pct: +24.7%  90th pct: +38.2%                           │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

### Behaviour

- The strategy dropdown is populated from the strategy registry.
- Selecting a strategy dynamically renders its parameter fields (from `StrategyConfig.parameters`) with default values pre-filled.
- "Run Backtest" validates inputs, fetches data, runs the engine, and displays the single-backtest tab.
- "Run Entry Sweep" validates inputs including sweep-specific parameters, fetches data for the full window, runs all sub-backtests, and displays the entry-sweep tab.
- Both buttons are disabled while a backtest or sweep is running. The sweep shows a progress bar indicating how many of the N entry-date runs have completed.
- Display validation errors (bad symbol, invalid dates, missing fields, holding period longer than data window) in a message box.
- The two charts in the single-backtest tab share the same x-axis so zooming/panning stays synchronised.
- Previous result tabs are replaced when a new run completes (one single-backtest tab and one sweep tab at most).

### Charts

**Portfolio Value chart (single backtest):**
- Y-axis: dollar value.
- Plot the strategy's portfolio value as a solid line.
- Overlay a buy-and-hold baseline normalised to the same initial cash.
- Mark buy trades with green up-triangles, sell trades with red down-triangles.

**Price chart (single backtest):**
- Y-axis: stock price.
- Plot the close price as a solid line.
- Mark buy and sell trades at their execution prices with the same triangle markers.

**Equity Curves chart (entry sweep):**
- X-axis: trading days since entry (integer, 0 = entry date) — not calendar dates, so all curves are aligned.
- Y-axis: normalised portfolio value (1.0 = initial investment).
- Each individual curve is a thin semi-transparent line, coloured on a green-to-red gradient based on its final return.
- A shaded band shows the 25th–75th percentile envelope across all curves at each time step.
- A dashed black line shows the median curve.
- A horizontal grey line at 1.0 marks the breakeven level.

**Return Distribution chart (entry sweep):**
- A histogram of final returns (%) across all entry dates.
- A vertical dashed line at 0% marks breakeven.
- A vertical solid line at the median return, labelled with the value.

## Persistence

### Saving and loading backtest configurations

The application saves and loads backtest configurations (not results) as JSON files via a File menu.

Configuration file format:
```json
{
  "symbol": "AAPL",
  "strategy": "SMA Crossover",
  "parameters": {"short_window": 20, "long_window": 50},
  "interval": "1d",
  "start_date": "2023-01-01",
  "end_date": "2025-01-01",
  "initial_cash": 10000,
  "sweep": {
    "holding_period_days": 252,
    "entry_step_days": 20
  }
}
```

The File menu provides:
- **Save Configuration** — saves current control panel state to a JSON file (file dialog).
- **Load Configuration** — loads a JSON file and populates the control panel fields.

### Exporting results

After a backtest or sweep completes, the user can export results:
- **Export Chart as PNG** — saves the currently visible tab's charts to a PNG file.
- **Export Trade Log as CSV** — saves the single-backtest trade log as a CSV file (entry date, exit date, entry price, exit price, shares, P&L, return, duration).
- **Export Sweep Summary as CSV** — saves the per-entry-date final returns and the aggregate statistics.

These export options appear in the File menu and are only enabled when results exist.

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12+ |
| Market data | yfinance |
| Data manipulation | pandas |
| Plotting | matplotlib |
| GUI toolkit | tkinter (stdlib) |
| Package manager | uv (pyproject.toml with uv dependency groups) |

No web framework, no database, no external services beyond Yahoo Finance. All technical indicators are computed using pandas — no external indicator libraries.

## Project Structure

```
backtester/
├── pyproject.toml
├── src/
│   └── backtester/
│       ├── __init__.py
│       ├── __main__.py          # entry point: python -m backtester
│       ├── data.py              # yfinance data fetching, caching, validation
│       ├── engine.py            # backtest loop, portfolio, metrics
│       ├── sweep.py             # entry-time sweep runner and aggregation
│       ├── indicators.py        # SMA, EMA, RSI, MACD, Bollinger — pure pandas
│       ├── persistence.py       # config save/load, result export (JSON, CSV, PNG)
│       ├── strategy/
│       │   ├── __init__.py      # Strategy base class, Signal enum, registry
│       │   ├── sma_crossover.py
│       │   ├── rsi_reversion.py
│       │   ├── macd_crossover.py
│       │   ├── bollinger_breakout.py
│       │   └── buy_and_hold.py
│       └── gui/
│           ├── __init__.py
│           ├── app.py           # main window, menu bar, tab container
│           ├── controls.py      # input panel, strategy parameter fields
│           ├── backtest_tab.py  # single-backtest result charts and summary
│           ├── sweep_tab.py     # entry-sweep equity curves and histogram
│           └── trade_table.py   # scrollable trade log table widget
└── tests/
    ├── test_data.py
    ├── test_engine.py
    ├── test_sweep.py
    ├── test_indicators.py
    ├── test_strategies.py
    └── test_persistence.py
```

## Entry Point

```
uv run python -m backtester
```

This launches the tkinter GUI. There is no CLI mode; the GUI is the only interface.
