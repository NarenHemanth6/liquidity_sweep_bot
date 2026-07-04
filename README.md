# Liquidity Sweep Bot (v1 — Paper/Simulation Only)

An educational, US large-cap day-trading bot that detects liquidity
sweep / reversal setups (PMH, PML, PDH, PDL, VWAP reclaim, wick
rejection) with QQQ confirmation, risk-based position sizing, and
daily kill-switch controls.

## ⚠️ Status: simulation only

**This version does not place real trades and cannot place real trades.**

- The only broker implementation is `src/broker/paper_broker.py`, a pure
  in-process simulator. It makes no network calls and holds no credentials.
- `config/settings.yaml` defaults `mode.trading_mode` to `"paper"` and
  `mode.enable_live_trading` to `false`.
- There is no live broker adapter in this codebase. A future version
  would need to add one explicitly, gated by **both** a config flag and
  an `ENABLE_LIVE_TRADING=true` environment variable, defaulting to
  disabled. Until that exists, live trading is simply not possible with
  this code, regardless of any flag you set.

## Project structure

```
liquidity_sweep_bot/
├── config/
│   ├── settings.yaml      # strategy, risk, session, broker settings
│   └── watchlist.yaml     # candidate symbol universe
├── data/
│   ├── raw/               # place your own real historical CSVs here (git-ignored)
│   ├── processed/         # optional cleaned/derived CSVs (git-ignored)
│   ├── examples/          # committed synthetic example CSVs
│   └── README.md          # CSV schema, validation, and backtest-workflow docs
├── src/
│   ├── config_loader.py   # loads YAML + env vars, never hardcodes secrets
│   ├── watchlist.py       # filters candidates by price/market-cap
│   ├── market_levels.py   # PMH / PML / PDH / PDL / VWAP
│   ├── candle_features.py # wick ratios, body size, CLV, volume spike
│   ├── strategy/
│   │   └── liquidity_sweep.py   # long/short setup detection -> TradeSignal
│   ├── risk/
│   │   ├── position_sizing.py   # 0.333% risk sizing, spread/qty rejection
│   │   └── risk_controls.py     # daily kill-switch, trade/time limits
│   ├── broker/
│   │   └── paper_broker.py      # simulated fills, stops, targets — NO live orders
│   ├── journal/
│   │   └── trade_journal.py     # CSV trade log
│   ├── backtesting/
│   │   ├── data_loader.py       # historical CSV loader
│   │   ├── data_validation.py   # CSV schema/integrity checks
│   │   ├── engine.py            # multi-day backtest engine (PaperBroker only)
│   │   └── metrics.py           # win rate, profit factor, drawdown, etc.
│   └── main.py             # wires it all together for a session
├── scripts/
│   ├── run_sample_simulation.py    # one-day paper sim on sample_data/
│   ├── run_backtest.py             # multi-day backtest on sample_data/backtest/
│   ├── validate_data.py            # validates CSVs in data/raw/
│   └── run_real_csv_backtest.py    # multi-day backtest on data/raw/ (your own CSVs)
├── tests/                  # unit tests per module
├── logs/                   # generated at runtime (git-ignored)
├── requirements.txt
├── .env.example            # template only, no real secrets
└── .gitignore
```

## Strategy summary

- **Universe**: US large-caps, price > $100, market cap > $1B, 09:35–13:00 ET.
- **Long setup**: sweep below PML/PDL → close back above → lower wick
  ratio ≥ 0.50 → volume ≥ 1.5x average → QQQ bullish/neutral → entry
  above rejection candle high, stop below wick low, targets at 2.5R/3R.
- **Short setup**: mirror image around PMH/PDH with upper wick ratio.
- **Position sizing**: risk 0.333% of equity per trade; reject if
  resulting quantity < 1 or spread too wide.
- **Kill switches**: max 3 trades/day, max 1% daily loss, halt after 2
  consecutive losses, no new entries after 12:45 ET, force-flat by
  13:00 ET.

## Sample simulation (paper mode)

`sample_data/` contains fully synthetic, fabricated OHLCV minute bars —
not real market data — for a fictional stock (`DEMO`, priced above
$100) and QQQ, covering one prior day plus a full simulation day. The
data has two liquidity-sweep setups deliberately built in: a long
setup sweeping the previous-day low that runs to its 2.5R target, and
a short setup sweeping the premarket high that gets stopped out. This
demonstrates both a winning and a losing trade end-to-end.

Regenerate the sample data (deterministic, fixed random seed):

```bash
python -m sample_data.generate_sample_data
```

Run the sample simulation and print a full report for each trade:

```bash
python -m scripts.run_sample_simulation
```

This exercises the exact same paper-trading pipeline as `src.main`
(`run_session`) — market levels, candle features, QQQ confirmation,
strategy detection, position sizing, risk controls, and `PaperBroker`
— and writes results to `logs/sample_trade_journal.csv`. It never
connects to a broker or places a real order.

## Historical backtesting (paper/simulation only)

`src/backtesting/` runs the same strategy/risk/`PaperBroker` pipeline
across many historical trading days at once, resetting risk controls
(max trades/day, max daily loss %, consecutive-loss halt) fresh every
day while account equity compounds across the whole run.

**Synthetic multi-day sample** (`sample_data/backtest/`, generated by
`sample_data/backtest/generate_backtest_data.py`): 3 trading days —
one history-only day, one day with a winning and a losing trade, and
one day with no valid setup.

```bash
python -m scripts.run_backtest
```

Prints total trades, win rate, gross/net P&L, average win/loss, profit
factor, max drawdown, and ending equity, and writes
`logs/backtest_trade_journal.csv`.

**Your own historical CSV files** — see `data/README.md` for the full
workflow (required schema, validation, and the extended report). In
short:

```bash
# 1. Drop your own {SYMBOL}_bars.csv files (plus QQQ_bars.csv) into data/raw/
# 2. Validate them:
python -m scripts.validate_data
# 3. Backtest them:
python -m scripts.run_real_csv_backtest
# ...or try the bundled synthetic example data first, with no setup required:
python -m scripts.run_real_csv_backtest --data-dir data/examples
```

`scripts/run_real_csv_backtest.py` refuses to run if validation fails
or no QQQ (confirmation-symbol) file is found, and additionally prints
best/worst trade, trades per symbol, and daily P&L. Everything here —
like every other script in this project — only ever exercises
`PaperBroker`; no network access, broker connection, or credentials are
involved anywhere in this path, and no real market data is downloaded.

## Running tests

```bash
python -m pytest -q
```

## Setup (once implementation is complete)

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # fill in any data-provider keys later; not required for paper mode
```

## Running in paper mode

```bash
python -m src.main
```

This will refuse to start unless `config/settings.yaml` has
`mode.trading_mode: "paper"` — which is the default and, in v1, the
**only** supported mode.

## Security notes

- No API keys, passwords, or account numbers are ever hardcoded.
- All sensitive values are read from environment variables via a local
  `.env` file, which is git-ignored (`.env.example` is the committed
  template).
- `logs/` output (trade journal, order log) is git-ignored since it may
  contain account-specific simulated P&L data.

## Roadmap (not in this version)

- Downloading real market data from the internet (only local,
  manually-placed CSV files are supported today — see `data/README.md`)
- Real-time market data adapter
- Live broker adapter (explicitly gated, off by default)
- Web/CLI dashboard for the trade journal
