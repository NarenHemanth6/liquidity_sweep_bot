# Historical CSV Data

This project is **paper/simulation only**. Nothing in this folder, or
any script that reads it, can place a real order, connect to a broker,
or use any account credentials. The only simulated execution path is
`src/broker/paper_broker.py` via `src/backtesting/engine.py` -- there
is no live broker adapter anywhere in this codebase.

## Folder layout

```
data/
├── raw/          # place your own historical minute-bar CSV files here
├── processed/    # optional: cleaned/derived CSVs you produce from raw/
└── examples/     # small, fully synthetic example CSVs (not real market data)
```

- `data/raw/` -- intentionally empty in the repository (only a
  `.gitkeep` placeholder). Any real CSV files you drop in here stay
  **untracked** (see `.gitignore`) -- they are never committed.
- `data/processed/` -- same treatment; empty in the repo, your own
  output files stay untracked.
- `data/examples/` -- committed on purpose. Fabricated OHLCV data for
  a fictional stock (`DEMO`) and `QQQ`, demonstrating the required
  schema and the `scripts/run_real_csv_backtest.py` workflow without
  needing any real market data.

## Required CSV schema

Every file must be a plain CSV with this header, one row per
one-minute bar:

```
timestamp,symbol,open,high,low,close,volume
```

Example row:

```
2026-07-01 09:30:00,AAPL,150.12,150.45,150.02,150.30,128300
```

- `timestamp` -- e.g. `2026-07-01 09:30:00`. Any format
  `pandas.to_datetime` can parse; naive (no UTC offset) timestamps are
  assumed to be `America/New_York`.
- `symbol` -- the ticker this row belongs to, e.g. `AAPL` or `QQQ`.
- `open`, `high`, `low`, `close` -- numeric prices; `high` must be the
  highest and `low` the lowest of the four OHLC values on every row.
- `volume` -- numeric share volume.

One file per symbol, named `{SYMBOL}_bars.csv` (e.g. `AAPL_bars.csv`,
`QQQ_bars.csv`) -- see `src/backtesting/data_loader.py`. A
`{CONFIRMATION_SYMBOL}_bars.csv` file (default `QQQ_bars.csv`) is
always required; the strategy uses it for directional confirmation.

## Validating your data

Before backtesting, validate every file in `data/raw/`:

```bash
.venv\Scripts\python.exe -m scripts.validate_data
```

This checks, per file: required columns are present, every timestamp
parses, every symbol is present, OHLCV columns are numeric, there are
no duplicate `(timestamp, symbol)` rows, `high >= low`, `high >= open`
and `high >= close`, `low <= open` and `low <= close`; rows not sorted
ascending by timestamp are reported as a warning only (the loader
sorts automatically). At the directory level it also confirms a
confirmation-symbol file exists.

Point it at any other directory with `--data-dir`, e.g.:

```bash
.venv\Scripts\python.exe -m scripts.validate_data --data-dir data/examples
```

## Running a backtest against your CSVs

```bash
.venv\Scripts\python.exe -m scripts.run_real_csv_backtest
```

This validates `data/raw/` first and refuses to run if validation
fails or no confirmation-symbol file is present. It then discovers
every other `{SYMBOL}_bars.csv` file, runs the liquidity sweep strategy
through `src.backtesting.engine.run_backtest` (PaperBroker-simulated
fills only -- no real orders, ever), and prints total trades, win
rate, net P&L, profit factor, max drawdown, ending equity, the best and
worst trade, trades per symbol, and daily P&L. The full per-trade
journal is written to `logs/real_csv_backtest_journal.csv`.

To try the workflow immediately with the bundled synthetic example
data instead of your own files:

```bash
.venv\Scripts\python.exe -m scripts.run_real_csv_backtest --data-dir data/examples
```

## Reminder

This is a **paper/simulation-only** project. No live broker
connection, no IBKR integration, no Trade The Pool integration, no real
order placement, and no market-data download exist anywhere in this
codebase. Everything here reads local CSV files only.
