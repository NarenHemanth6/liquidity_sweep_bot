"""
sample_data/generate_sample_data.py

Generates deterministic, fully synthetic (fake, not real market data)
one-minute OHLCV bars for:
  - a fictional large-cap stock, symbol "DEMO", priced above $100
  - QQQ, used only as the directional confirmation symbol

The data spans two trading days:
  - Day 1 (2026-06-30): a full prior regular session, used to establish
    PDH (previous day high) and PDL (previous day low).
  - Day 2 (2026-07-01): premarket (establishes PMH/PML) plus the
    regular session, with exactly two hand-placed liquidity-sweep
    setups baked into otherwise-random price action:
      1. A LONG setup: price sweeps below PDL, reclaims, and rallies
         to hit the 2.5R take-profit target (a winning trade).
      2. A SHORT setup: price sweeps above PMH, reclaims, then rallies
         back through the stop (a losing trade) — included
         deliberately so the sample demonstrates both a win and a
         loss exit path.

All price/volume values are entirely fabricated for demonstration and
testing purposes; this is not real market data for any real security.

Running this file directly regenerates:
    sample_data/DEMO_bars.csv
    sample_data/QQQ_bars.csv
"""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

TZ = ZoneInfo("America/New_York")
SYMBOL = "DEMO"

DAY1 = "2026-06-30"  # previous trading day -> PDH / PDL
DAY2 = "2026-07-01"  # simulation day -> PMH / PML + the two setups

SEED = 42


def _baseline_bars(
    timestamps: pd.DatetimeIndex,
    start_price: float,
    low_bound: float,
    high_bound: float,
    rng: np.random.Generator,
    price_std: float = 0.06,
    wick_spread: float = 0.05,
    vol_low: int = 850,
    vol_high: int = 1150,
) -> pd.DataFrame:
    """Generate quiet, random-walk baseline OHLCV bars clipped to a range.

    The range is kept comfortably inside any liquidity level used by
    the strategy so baseline noise never accidentally triggers a
    sweep/reclaim on its own; only explicitly overridden bars do.

    Args:
        timestamps: Bar timestamps (tz-aware, ascending, evenly spaced).
        start_price: Starting close price for the random walk.
        low_bound: Lower clip bound for closes.
        high_bound: Upper clip bound for closes.
        rng: A seeded numpy random Generator for reproducibility.
        price_std: Std-dev of each 1-minute close-to-close step.
        wick_spread: Max additional high/low wick beyond the body.
        vol_low: Minimum per-bar volume.
        vol_high: Maximum per-bar volume (kept below any 1.5x spike
            multiple relative to this range's own average).

    Returns:
        A DataFrame with columns timestamp, open, high, low, close, volume.
    """
    n = len(timestamps)
    steps = rng.normal(loc=0.0, scale=price_std, size=n)
    closes = start_price + np.cumsum(steps)
    closes = np.clip(closes, low_bound, high_bound)

    opens = np.empty(n)
    opens[0] = start_price
    opens[1:] = closes[:-1]

    highs = np.maximum(opens, closes) + np.abs(rng.normal(0, wick_spread / 2, n))
    lows = np.minimum(opens, closes) - np.abs(rng.normal(0, wick_spread / 2, n))
    volumes = rng.integers(vol_low, vol_high, size=n)

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


def _ramp_bars(
    start_time: pd.Timestamp,
    start_price: float,
    end_price: float,
    n_bars: int,
    volume: int,
) -> pd.DataFrame:
    """Generate a smooth directional ramp of bars from start to end price.

    Used to carry price from a trigger bar to a stop or target level
    over the following few minutes, so the paper broker has a clean,
    deterministic path to simulate a fill against.

    Args:
        start_time: Timestamp of the first ramp bar (one minute after
            the trigger bar).
        start_price: Close price to ramp from (typically the trigger
            bar's close).
        end_price: Close price to ramp to (at/through the target or
            stop level).
        n_bars: Number of one-minute bars in the ramp.
        volume: Constant volume for each ramp bar (kept below the spike
            threshold so it doesn't itself re-trigger a scan).

    Returns:
        A DataFrame with columns timestamp, open, high, low, close, volume.
    """
    timestamps = pd.date_range(start=start_time, periods=n_bars, freq="1min", tz=TZ)
    fractions = np.linspace(1.0 / n_bars, 1.0, n_bars)
    closes = start_price + fractions * (end_price - start_price)
    opens = np.empty(n_bars)
    opens[0] = start_price
    opens[1:] = closes[:-1]
    highs = np.maximum(opens, closes) + 0.04
    lows = np.minimum(opens, closes) - 0.03
    volumes = np.full(n_bars, volume)

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


def generate_sample_bars() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the full DEMO stock and QQQ sample datasets.

    Returns:
        (stock_bars, qqq_bars): Two DataFrames, each with columns
        timestamp, open, high, low, close, volume, sorted ascending
        by timestamp.
    """
    rng = np.random.default_rng(SEED)

    # ---------------------------------------------------------------
    # Day 1 (previous day) regular session: 09:30 - 15:59 ET
    # Establishes PDH = 155.00 and PDL = 148.00 via explicit overrides.
    # ---------------------------------------------------------------
    day1_ts = pd.date_range(f"{DAY1} 09:30", f"{DAY1} 15:59", freq="1min", tz=TZ)
    day1 = _baseline_bars(day1_ts, start_price=151.0, low_bound=149.2, high_bound=153.8, rng=rng)

    pdh_idx = 45  # 10:15 ET
    day1.loc[pdh_idx, ["open", "high", "low", "close"]] = [154.80, 155.00, 154.70, 154.90]

    pdl_idx = 300  # 14:30 ET
    day1.loc[pdl_idx, ["open", "high", "low", "close"]] = [148.30, 148.40, 148.00, 148.20]

    # ---------------------------------------------------------------
    # Day 2 premarket: 04:00 - 09:29 ET
    # Establishes PMH = 152.00 and PML = 149.00 via explicit overrides.
    # ---------------------------------------------------------------
    day2_pm_ts = pd.date_range(f"{DAY2} 04:00", f"{DAY2} 09:29", freq="1min", tz=TZ)
    day2_pm = _baseline_bars(
        day2_pm_ts, start_price=150.5, low_bound=149.6, high_bound=151.4, rng=rng
    )

    pmh_idx = 100  # 05:40 ET
    day2_pm.loc[pmh_idx, ["open", "high", "low", "close"]] = [151.80, 152.00, 151.70, 151.90]

    pml_idx = 250  # 08:10 ET
    day2_pm.loc[pml_idx, ["open", "high", "low", "close"]] = [149.30, 149.40, 149.00, 149.20]

    # ---------------------------------------------------------------
    # Day 2 regular session: 09:30 - 13:05 ET
    # Contains the two hand-placed liquidity sweep setups.
    # ---------------------------------------------------------------
    day2_reg_ts = pd.date_range(f"{DAY2} 09:30", f"{DAY2} 13:05", freq="1min", tz=TZ)
    day2_reg = _baseline_bars(
        day2_reg_ts, start_price=150.5, low_bound=149.8, high_bound=151.2, rng=rng
    )

    # --- LONG setup: sweep below PDL (148.00), reclaim, rally to target ---
    long_idx = 35  # 10:05 ET
    day2_reg.loc[long_idx, ["open", "high", "low", "close", "volume"]] = [
        148.55, 148.70, 147.80, 148.60, 2000,
    ]
    # entry = 148.71, stop = 147.79, risk = 0.92, target(2.5R) = 151.01
    long_ramp = _ramp_bars(
        start_time=day2_reg_ts[long_idx] + pd.Timedelta(minutes=1),
        start_price=148.60,
        end_price=151.15,
        n_bars=12,
        volume=1000,
    )
    for _, row in long_ramp.iterrows():
        match = day2_reg["timestamp"] == row["timestamp"]
        day2_reg.loc[match, ["open", "high", "low", "close", "volume"]] = [
            row["open"], row["high"], row["low"], row["close"], row["volume"],
        ]

    # --- SHORT setup: sweep above PMH (152.00), reclaim, then stop out ---
    short_idx = 105  # 11:15 ET
    day2_reg.loc[short_idx, ["open", "high", "low", "close", "volume"]] = [
        151.65, 152.30, 151.55, 151.60, 2100,
    ]
    # entry = 151.54, stop = 152.31, risk = 0.77, target(2.5R) = 149.615
    short_ramp = _ramp_bars(
        start_time=day2_reg_ts[short_idx] + pd.Timedelta(minutes=1),
        start_price=151.60,
        end_price=152.55,
        n_bars=8,
        volume=1000,
    )
    for _, row in short_ramp.iterrows():
        match = day2_reg["timestamp"] == row["timestamp"]
        day2_reg.loc[match, ["open", "high", "low", "close", "volume"]] = [
            row["open"], row["high"], row["low"], row["close"], row["volume"],
        ]

    stock_bars = pd.concat([day1, day2_pm, day2_reg], ignore_index=True)
    stock_bars = stock_bars.sort_values("timestamp").reset_index(drop=True)

    # ---------------------------------------------------------------
    # QQQ: aligned to Day 2 (premarket + regular) timestamps only.
    # Bars for Day 1 are intentionally omitted; the strategy never
    # scans Day 1 bars for signals in this sample (no matching QQQ
    # row means no scan), which keeps the sample focused on Day 2.
    # ---------------------------------------------------------------
    qqq_ts = pd.concat(
        [pd.Series(day2_pm_ts), pd.Series(day2_reg_ts)], ignore_index=True
    )
    qqq_bars = _baseline_bars(
        pd.DatetimeIndex(qqq_ts),
        start_price=500.0,
        low_bound=498.0,
        high_bound=502.0,
        rng=rng,
        price_std=0.08,
        wick_spread=0.05,
        vol_low=5_000_000,
        vol_high=6_000_000,
    )

    # Bullish QQQ bar at the LONG trigger's timestamp (+0.14% move).
    long_trigger_ts = day2_reg_ts[long_idx]
    match = qqq_bars["timestamp"] == long_trigger_ts
    qqq_bars.loc[match, ["open", "close"]] = [500.00, 500.70]

    # Bearish QQQ bar at the SHORT trigger's timestamp (-0.14% move).
    short_trigger_ts = day2_reg_ts[short_idx]
    match = qqq_bars["timestamp"] == short_trigger_ts
    qqq_bars.loc[match, ["open", "close"]] = [501.00, 500.30]

    qqq_bars = qqq_bars.sort_values("timestamp").reset_index(drop=True)

    return stock_bars, qqq_bars


def main() -> None:
    """Generate the sample bars and write them to CSV files in this folder."""
    stock_bars, qqq_bars = generate_sample_bars()

    out_dir = Path(__file__).parent
    stock_path = out_dir / f"{SYMBOL}_bars.csv"
    qqq_path = out_dir / "QQQ_bars.csv"

    stock_bars.to_csv(stock_path, index=False)
    qqq_bars.to_csv(qqq_path, index=False)

    print(f"Wrote {len(stock_bars)} {SYMBOL} bars to {stock_path}")
    print(f"Wrote {len(qqq_bars)} QQQ bars to {qqq_path}")


if __name__ == "__main__":
    main()
