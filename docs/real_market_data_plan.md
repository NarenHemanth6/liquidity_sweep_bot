# Real Market Data Plan

**Status: planning only. No data is downloaded by this document, and no
code in this repository connects to any external data provider yet.**
This is a preparation plan for a future stage — importing real
1-minute historical market data as local CSV files, so the existing
backtester (`src/backtesting/`) can be run against real symbols
instead of only synthetic sample/example data.

## Safety scope of this stage

- No broker execution of any kind.
- No IBKR connection.
- No Trade The Pool connection.
- No orders are placed, real or simulated-via-broker.
- No API keys are stored in code — only optional, unused placeholders
  in `.env.example` (see below).
- This project remains **paper/simulation only**. The only execution
  path that exists is `src/broker/paper_broker.py`, driven by
  `src/backtesting/engine.py`. Nothing about real data import changes
  that.
- This stage does not perform any download. It documents *how* real
  data would be acquired and *where* it would go, so that when data is
  eventually added (by you, manually, or in a later approved stage),
  the project already knows what to do with it.

## Recommended first test symbols

A small, liquid, well-known set to validate the pipeline against
before scaling up:

| Symbol | Role |
|--------|------|
| `NVDA` | tradable candidate |
| `TSLA` | tradable candidate |
| `AAPL` | tradable candidate |
| `MSFT` | tradable candidate |
| `QQQ`  | **mandatory** — directional confirmation symbol |

`QQQ` is not optional: `src/strategy/liquidity_sweep.py`'s
`qqq_direction()` and every entry point in `src/backtesting/engine.py`
require a confirmation-symbol file to be present, and
`src/backtesting/data_validation.py` / `scripts/validate_data.py`
already fail validation if it's missing (see
`test_validate_directory_missing_confirmation_file_fails` in
`tests/test_data_validation.py`).

## Required timeframe

**1-minute OHLCV bars.** This matches the strategy's bar-by-bar sweep
detection and the session windowing already implemented
(`config/settings.yaml`'s `session_start`/`session_end`,
`no_new_trades_after`, `force_flat_time`, all expressed in "HH:MM"
minute granularity). Coarser bars (5-min, daily, etc.) are out of
scope — the strategy would not detect the same setups.

## Required columns

Every CSV file must use exactly this header, matching
`src/backtesting/data_loader.REQUIRED_COLUMNS` and
`src/backtesting/data_validation.REQUIRED_COLUMNS`:

```
timestamp,symbol,open,high,low,close,volume
```

- `timestamp` — e.g. `2026-07-01 09:30:00`. Naive timestamps are
  assumed to be `America/New_York` (see `data/README.md`).
- `symbol` — the ticker for that row, e.g. `NVDA` or `QQQ`.
- `open`, `high`, `low`, `close` — numeric prices; `high` must be the
  session-bar maximum and `low` the minimum of the four OHLC values.
- `volume` — numeric share volume.

## Required trading-session coverage

Two coverage requirements, both already assumed by
`src/market_levels.py` and `src/backtesting/engine.py`:

1. **Premarket data, if available** — used to compute PMH (premarket
   high) and PML (premarket low). `config/settings.yaml`'s
   `market_levels.premarket_start`/`premarket_end` (`04:00`–`09:30`
   ET) defines this window. If a provider cannot supply premarket
   bars for a symbol, the backtester still runs off PDH/PDL alone (see
   `MarketLevels.compute_all`'s existing `try/except` around PDH/PDL),
   but PMH/PML-based setups won't be detected for that symbol/day.
2. **Regular market hours, for trade simulation** — `09:30`–`16:00` ET
   at minimum, so the strategy's `09:35`–`13:00` trading window (per
   `config/settings.yaml`'s `session_start`/`session_end`) and the
   prior day's regular session (needed for PDH/PDL) are both fully
   covered. Bars from `13:00` to market close are harmless to include
   even though the strategy doesn't trade past `13:00` in this
   version — the engine simply won't scan them.

At least **two consecutive trading days** of data are required per
symbol: the backtester's earliest calendar date is always
history-only (used solely to establish PDH/PDL for the next day — see
`src/backtesting/engine.py`'s `tradable_dates = all_dates[1:]`), so a
single day of data would produce zero tradable days.

## Where the data goes

Real CSV files are placed manually into `data/raw/`, one file per
symbol, named `{SYMBOL}_bars.csv` (e.g. `NVDA_bars.csv`,
`QQQ_bars.csv`) — see `data/raw/README.md` for the exact naming
convention and `data/README.md` for the full schema reference. Nothing
in `data/raw/` is committed to git except the `.gitkeep` placeholder
(see `.gitignore`); real market data files stay local and untracked.

(As of `scripts/download_ibkr_bars.py`, `{SYMBOL}_1min.csv` is a second
recognized naming convention — see `docs/ibkr_historical_data_setup.md`
— for files downloaded directly from IBKR rather than acquired
manually. Both conventions validate and backtest with no rename step.)

## No real broker connection required

Acquiring historical 1-minute bars from a market-data provider (e.g.
a REST API export, a downloaded CSV from a data vendor's website, or a
local export from a charting platform) does **not** require, and must
never be confused with, a live brokerage connection. This plan only
concerns *historical, already-closed* bar data landing as flat CSV
files on local disk — never a live quote stream, an order-routing
connection, or any brokerage/prop-firm account (no IBKR, no Trade The
Pool, no other broker integration of any kind).

## Suggested next steps (not part of this stage)

These are **future, separate, explicitly-approved stages** — nothing
below is implemented or authorized by this document:

1. Choose one data provider (e.g. a REST historical-data API) and
   confirm it can export 1-minute OHLCV bars, ideally including
   premarket, for the symbols above.
2. Manually export/download CSVs for `NVDA`, `TSLA`, `AAPL`, `MSFT`,
   and `QQQ` covering at least a few trading days.
3. Reformat the export (if needed) to match the required column
   schema exactly, and place the files in `data/raw/`.
4. Run `python -m scripts.validate_data` and fix any reported errors.
5. Run `python -m scripts.run_real_csv_backtest` and review the
   printed report and `logs/real_csv_backtest_journal.csv`.

Any future stage that adds an *automated* download (API client code,
stored credentials, scheduled fetch jobs) is a distinct, separate piece
of work requiring its own explicit approval — it is out of scope here.
