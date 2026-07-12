# IBKR Historical Data Setup

This document covers how to set up TWS or IB Gateway so that
`scripts/download_ibkr_bars.py` can download **closed historical
1-minute bars only**, and land them as local CSV files for
`scripts/validate_data.py` / `scripts/run_real_csv_backtest.py`.

## Safety scope

- **Historical data only.** The downloader calls IBKR's
  `reqHistoricalData` and nothing else. It never calls `placeOrder`,
  `cancelOrder`, or any other order-routing method, and never requests
  account, portfolio, or position data.
- **No live trading.** This project's only execution path remains
  `src/broker/paper_broker.py`. The downloader does not touch that
  code at all — it only produces CSV files on local disk.
- **No Trade The Pool, no Alpaca, no Webull.** This stage is IBKR
  historical-data-only.
- **No credentials or account numbers.** `IBKR_HOST`, `IBKR_PORT`, and
  `IBKR_CLIENT_ID` are local connection settings for a TWS/IB Gateway
  instance running on your own machine — not an account number, API
  key, username, or password. Nothing in this codebase reads or stores
  any of those.

## 1. Install TWS or IB Gateway

Download and install either:

- **Trader Workstation (TWS)** — the full desktop application, or
- **IB Gateway** — a lighter-weight, headless alternative

from Interactive Brokers. Either works identically for this script;
IB Gateway is recommended if you don't need the TWS UI.

## 2. Use a paper trading account for this

Log in to TWS/IB Gateway with a **paper trading** account/mode, not a
live account. This project is paper/simulation only end-to-end, and
using a paper login means there is no live account behind the
connection at all, even in principle.

## 3. Enable the API and set the socket port

In TWS/IB Gateway: **File → Global Configuration → API → Settings**

- Check **"Enable ActiveX and Socket Clients"**.
- Note the **Socket port**:
  - TWS paper trading default: **7497**
  - TWS live trading default: 7496 (do not use this for this project)
  - IB Gateway paper trading default: 4002
  - IB Gateway live trading default: 4001
- Under **"Trusted IP Addresses"**, add `127.0.0.1` if connecting from
  the same machine (the default assumption for this script).
- It is recommended to also check **"Read-Only API"** in this same
  settings panel. This is an IBKR-side safeguard that makes the API
  connection reject order-related requests at the gateway itself, on
  top of the fact that this script never sends any.

## 4. Configure connection settings locally

Copy `.env.example` to `.env` (git-ignored, never committed) and set:

```
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=101
```

Use the port matching your TWS/IB Gateway paper-trading setup from
step 3. `IBKR_CLIENT_ID` just needs to be a number not already in use
by another API client connected to the same TWS/IB Gateway session —
101 is an arbitrary default.

## 5. Install the `ibapi` dependency

```bash
pip install -r requirements.txt
```

This installs `ibapi`, IBKR's official Python API client.

## 6. Run the downloader

With TWS/IB Gateway running and logged in to a paper account:

```bash
.venv\Scripts\python.exe -m scripts.download_ibkr_bars --symbols QQQ NVDA TSLA AAPL --start 2026-07-01 --end 2026-07-01 --bar-size "1 min" --output-dir data/raw --host 127.0.0.1 --port 7497 --client-id 101
```

This writes one file per symbol into `data/raw/`:

```
QQQ_1min.csv
NVDA_1min.csv
TSLA_1min.csv
AAPL_1min.csv
```

## 7. Validate and backtest

`scripts/validate_data.py` and `scripts/run_real_csv_backtest.py`
recognize `{SYMBOL}_1min.csv` files directly — no rename step needed.
(They also still recognize the original `{SYMBOL}_bars.csv` convention
used by manually-acquired CSVs; see `data/raw/README.md`.)

```bash
.venv\Scripts\python.exe -m scripts.validate_data
.venv\Scripts\python.exe -m scripts.run_real_csv_backtest
```

## Troubleshooting

- **`[DOWNLOAD FAILED] Could not connect to IBKR TWS/IB Gateway ...`**
  — TWS/IB Gateway is not running, not logged in, the API is not
  enabled (step 3), or the port doesn't match. Confirm the socket port
  in TWS/IB Gateway's API settings matches `--port` / `IBKR_PORT`.
- **`IBKR returned an error for <symbol>: ...`** — usually a pacing
  violation (too many requests too quickly), an unrecognized symbol,
  or a date range with no available historical data. Reduce the
  number of symbols/date range per run, or check the symbol is valid
  on IBKR (`secType="STK"`, `exchange="SMART"`, `currency="USD"`).
- **Historical data pacing limits** — IBKR enforces request-pacing
  limits on `reqHistoricalData` (a maximum number of requests per
  rolling time window). This script requests symbols sequentially,
  one at a time, which is friendly to those limits for small symbol
  lists; very large symbol/date-range batches may still need to be
  split across multiple runs.
