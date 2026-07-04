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
│   └── main.py             # wires it all together for a session
├── tests/                  # unit tests per module
├── logs/                   # generated at runtime (git-ignored)
├── requirements.txt
├── .env.example            # template only, no real secrets
└── .gitignore
```

Every module above is currently a **stub** with a full docstring
describing its planned behavior, function signatures, and rules pulled
directly from the strategy spec. Implementation comes after this
structure is reviewed.

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

- Real-time market data adapter
- Live broker adapter (explicitly gated, off by default)
- Backtesting harness against historical bars
- Web/CLI dashboard for the trade journal
