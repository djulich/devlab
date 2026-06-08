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
| `engine` | Bar-by-bar backtest loop, portfolio tracking, metric computation. |
| `gui` | tkinter main window, parameter inputs, matplotlib result display. |

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

### Caching

Cache downloaded data in memory for the lifetime of the application so repeated backtests on the same symbol/interval/range do not re-fetch.

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

Ship with at least these three strategies so the GUI is immediately useful:

1. **SMA Crossover** — buy when a short simple moving average crosses above a long SMA; sell on the reverse crossover. Parameters: `short_window` (int, default 20), `long_window` (int, default 50).

2. **RSI Mean Reversion** — buy when RSI drops below an oversold threshold; sell when it rises above an overbought threshold. Parameters: `rsi_period` (int, default 14), `oversold` (float, default 30.0), `overbought` (float, default 70.0).

3. **Buy and Hold** — buy on the first bar, hold until the end. No parameters. Serves as the baseline benchmark.

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
| Number of trades | Count of executed buy+sell round trips. |
| Win rate (%) | Percentage of round-trip trades that were profitable. |

### Result data

Return a dataclass containing:

- The portfolio value series (DatetimeIndex → float).
- The price series for the symbol (for overlay plotting).
- The list of executed trades.
- The computed metrics dict.
- The strategy name and parameters used.
- The symbol, interval, and date range.

## GUI

Build with tkinter (stdlib). Embed matplotlib figures via `matplotlib.backends.backend_tkagg`.

### Layout

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
│  [ Run Backtest ]                                            │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ Portfolio Value Over Time (matplotlib figure)          │  │
│  │                                                        │  │
│  │  — Portfolio value                                     │  │
│  │  — Buy & hold baseline (normalised to same start)      │  │
│  │  ▲ Buy markers   ▼ Sell markers                        │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ Price Chart (matplotlib figure)                        │  │
│  │                                                        │  │
│  │  — Close price                                         │  │
│  │  ▲ Buy markers   ▼ Sell markers                        │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  Summary:                                                    │
│  Total return: +23.4%    Annualised: +11.2%                  │
│  Max drawdown: -8.7%     Sharpe ratio: 1.34                  │
│  Trades: 12              Win rate: 66.7%                     │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Behaviour

- The strategy dropdown is populated from the strategy registry.
- Selecting a strategy dynamically renders its parameter fields (from `StrategyConfig.parameters`) with default values pre-filled.
- Clicking "Run Backtest" validates inputs, fetches data, runs the engine, and displays results.
- While the backtest runs, disable the button and show a progress indicator.
- Display validation errors (bad symbol, invalid dates, missing fields) in a message box.
- The two matplotlib charts share the same x-axis (time) so zooming/panning stays synchronised.

### Charts

**Portfolio Value chart:**
- Y-axis: dollar value.
- Plot the strategy's portfolio value as a solid line.
- Overlay a buy-and-hold baseline normalised to the same initial cash.
- Mark buy trades with green up-triangles, sell trades with red down-triangles.

**Price chart:**
- Y-axis: stock price.
- Plot the close price as a solid line.
- Mark buy and sell trades at their execution prices with the same triangle markers.

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12+ |
| Market data | yfinance |
| Data manipulation | pandas |
| Plotting | matplotlib |
| GUI toolkit | tkinter (stdlib) |
| Package manager | uv (pyproject.toml with uv dependency groups) |

No web framework, no database, no external services beyond Yahoo Finance.

## Project Structure

```
backtester/
├── pyproject.toml
├── src/
│   └── backtester/
│       ├── __init__.py
│       ├── __main__.py          # entry point: python -m backtester
│       ├── data.py              # yfinance data fetching and caching
│       ├── engine.py            # backtest loop and metrics
│       ├── strategy/
│       │   ├── __init__.py      # Strategy base class, registry
│       │   ├── sma_crossover.py
│       │   ├── rsi_reversion.py
│       │   └── buy_and_hold.py
│       └── gui/
│           ├── __init__.py
│           ├── app.py           # main window
│           ├── controls.py      # input panel
│           └── charts.py        # matplotlib chart panel
└── tests/
    ├── test_data.py
    ├── test_engine.py
    └── test_strategies.py
```

## Entry Point

```
uv run python -m backtester
```

This launches the tkinter GUI. There is no CLI mode; the GUI is the only interface.
