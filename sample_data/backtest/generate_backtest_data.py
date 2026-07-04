"""
sample_data/backtest/generate_backtest_data.py

Generates deterministic, fully synthetic (fake, not real market data)
one-minute OHLCV bars for the historical backtester:
  - DEMO: a fictional large-cap stock, symbol "DEMO"
  - QQQ: used only as the directional confirmation symbol

Three trading days are produced:
  - Day 1 (2026-06-30): prior regular session only, used solely to
    establish Day 2's PDH/PDL. This date is history-only -- the
    backtester never scans the earliest calendar date in its dataset
    for trade signals (see src.backtesting.engine.run_backtest).
  - Day 2 (2026-07-01): premarket (-> PMH/PML) plus the regular
    session, with two hand-placed liquidity-sweep setups:
      1. A LONG setup that sweeps/reclaims PDL and rallies to the 2.5R
         take-profit target (a winning trade).
      2. A SHORT setup that sweeps/reclaims PMH, then reverses back
         through the stop (a losing trade).
  - Day 3 (2026-07-02): premarket + regular session with pure
    random-walk baseline price action only (no hand-placed overrides).
    Bounds are kept comfortably inside both Day 3's own PMH/PML and
    Day 2's PDH/PDL, and volume never reaches the spike threshold, so
    no sweep/reclaim condition is ever met -- a genuine "no valid
    setup" trading day.

All price/volume values are entirely fabricated for demonstration and
testing purposes; this is not real market data for any real security.

Running this file directly (re)writes:
    sample_data/backtest/DEMO_bars.csv
    sample_data/backtest/QQQ_bars.csv
Both files include a `symbol` column, matching the CSV schema expected
by src/backtesting/data_loader.py.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from sample_data.generate_sample_data import SYMBOL, TZ, _baseline_bars, generate_sample_bars

DAY3 = "2026-07-02"
SEED_DAY3 = 43


def generate_backtest_bars() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the full 3-trading-day DEMO stock and QQQ backtest datasets.

    Returns:
        (stock_bars, qqq_bars): each a DataFrame with columns
        timestamp, symbol, open, high, low, close, volume, sorted
        ascending by timestamp.
    """
    stock_bars, qqq_bars = generate_sample_bars()

    rng = np.random.default_rng(SEED_DAY3)

    # --- Day 3 premarket: establishes PMH3 / PML3; kept quiet. ---
    day3_pm_ts = pd.date_range(f"{DAY3} 04:00", f"{DAY3} 09:29", freq="1min", tz=TZ)
    day3_pm = _baseline_bars(
        day3_pm_ts, start_price=150.5, low_bound=149.6, high_bound=151.4, rng=rng
    )

    # --- Day 3 regular session: kept well inside Day 3's own PMH/PML
    # and Day 2's PDH/PDL, so no sweep/reclaim condition ever fires. ---
    day3_reg_ts = pd.date_range(f"{DAY3} 09:30", f"{DAY3} 13:05", freq="1min", tz=TZ)
    day3_reg = _baseline_bars(
        day3_reg_ts, start_price=150.4, low_bound=150.1, high_bound=150.9, rng=rng
    )

    day3_stock = pd.concat([day3_pm, day3_reg], ignore_index=True)
    day3_stock = day3_stock.sort_values("timestamp").reset_index(drop=True)

    day3_ts = pd.concat([pd.Series(day3_pm_ts), pd.Series(day3_reg_ts)], ignore_index=True)
    day3_qqq = _baseline_bars(
        pd.DatetimeIndex(day3_ts),
        start_price=500.0,
        low_bound=498.0,
        high_bound=502.0,
        rng=rng,
        price_std=0.08,
        wick_spread=0.05,
        vol_low=5_000_000,
        vol_high=6_000_000,
    )
    day3_qqq = day3_qqq.sort_values("timestamp").reset_index(drop=True)

    stock_bars = pd.concat([stock_bars, day3_stock], ignore_index=True)
    stock_bars = stock_bars.sort_values("timestamp").reset_index(drop=True)
    stock_bars.insert(1, "symbol", SYMBOL)

    qqq_bars = pd.concat([qqq_bars, day3_qqq], ignore_index=True)
    qqq_bars = qqq_bars.sort_values("timestamp").reset_index(drop=True)
    qqq_bars.insert(1, "symbol", "QQQ")

    return stock_bars, qqq_bars


def main() -> None:
    """Generate the backtest sample bars and write them to CSV files."""
    stock_bars, qqq_bars = generate_backtest_bars()

    out_dir = Path(__file__).parent
    stock_path = out_dir / f"{SYMBOL}_bars.csv"
    qqq_path = out_dir / "QQQ_bars.csv"

    stock_bars.to_csv(stock_path, index=False)
    qqq_bars.to_csv(qqq_path, index=False)

    print(f"Wrote {len(stock_bars)} {SYMBOL} bars to {stock_path}")
    print(f"Wrote {len(qqq_bars)} QQQ bars to {qqq_path}")


if __name__ == "__main__":
    main()
