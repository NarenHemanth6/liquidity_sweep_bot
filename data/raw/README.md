# data/raw/ — Place Your Real Historical CSV Files Here

**This project is paper/simulation only.** Nothing that reads this
folder can place a real order, connect to a broker, or use any account
credentials. See `docs/real_market_data_plan.md` for the full data
acquisition plan and `data/README.md` for the complete schema/workflow
reference.

This folder is intentionally empty in the repository (only this file
and a `.gitkeep` placeholder are tracked). Any real CSV files you place
here stay **untracked** — they are never committed (see `.gitignore`).

## One file per symbol

Place **one CSV file per symbol**, including the mandatory `QQQ`
confirmation file. The loader (`src/backtesting/data_loader.py`) and
validator (`src/backtesting/data_validation.py`) both expect the
`{SYMBOL}_bars.csv` naming convention used elsewhere in this project
(see `sample_data/backtest/` and `data/examples/`):

```
NVDA_bars.csv
TSLA_bars.csv
AAPL_bars.csv
MSFT_bars.csv
QQQ_bars.csv     <- mandatory, used for directional confirmation
```

If your provider exports files named differently (for example
`NVDA_1min.csv`, `TSLA_1min.csv`, `AAPL_1min.csv`, `MSFT_1min.csv`,
`QQQ_1min.csv`), rename them to the `{SYMBOL}_bars.csv` form above
before running validation or a backtest.

## Required schema

Every file needs this exact header, one row per one-minute bar:

```
timestamp,symbol,open,high,low,close,volume
```

Example row:

```
2026-07-01 09:30:00,NVDA,120.12,120.45,120.02,120.30,842300
```

See `data/README.md` for the full column reference, and
`docs/real_market_data_plan.md` for the recommended symbols, required
timeframe (1-minute bars), and session-coverage requirements
(premarket for PMH/PML, regular hours for trade simulation).

## Next steps once your files are here

```bash
.venv\Scripts\python.exe -m scripts.validate_data
.venv\Scripts\python.exe -m scripts.run_real_csv_backtest
```

The validator will refuse to pass (and the backtest script will refuse
to run) until every file's schema checks out and a `QQQ_bars.csv` file
is present.
