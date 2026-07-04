"""
backtesting/data_loader.py

Loads historical OHLCV minute-bar CSV files from local disk for the
backtester. This module only ever reads local files with pandas — no
network access, no broker connection, and no credentials of any kind
are involved anywhere in this file.

Expected CSV schema (header row required):
    timestamp, symbol, open, high, low, close, volume

`timestamp` may be timezone-naive or already timezone-aware; it is
localized/converted to the requested timezone (default
"America/New_York") since the strategy's session/premarket windowing
is timezone-sensitive.
"""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

REQUIRED_COLUMNS = ("timestamp", "symbol", "open", "high", "low", "close", "volume")

DEFAULT_TIMEZONE = "America/New_York"


def load_bars_csv(path: str | Path, timezone: str = DEFAULT_TIMEZONE) -> pd.DataFrame:
    """Load one historical OHLCV CSV file that includes a `symbol` column.

    Args:
        path: Path to the CSV file. May contain bars for one symbol or
            multiple symbols (e.g. a stock plus its QQQ confirmation
            data) stacked in the same file.
        timezone: IANA timezone to localize/convert the `timestamp`
            column into.

    Returns:
        A DataFrame with REQUIRED_COLUMNS, sorted ascending by
        timestamp, with `timestamp` tz-aware in `timezone`.

    Raises:
        FileNotFoundError: If `path` does not exist.
        ValueError: If the file has no rows or is missing any required
            column.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Historical data file not found: {path}")

    df = pd.read_csv(file_path)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} is missing required columns: {missing}")
    if df.empty:
        raise ValueError(f"{path} contains no rows")

    tz = ZoneInfo(timezone)
    ts = pd.to_datetime(df["timestamp"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(tz)
    else:
        ts = ts.dt.tz_convert(tz)
    df = df.assign(timestamp=ts)

    df["symbol"] = df["symbol"].astype(str)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)

    return df.sort_values("timestamp").reset_index(drop=True)


def filter_symbol(bars: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Return only the rows belonging to one symbol from a loaded frame.

    Args:
        bars: A DataFrame as returned by `load_bars_csv` (must have a
            `symbol` column).
        symbol: The ticker symbol to keep.

    Returns:
        A DataFrame containing only `symbol`'s rows, re-sorted by
        timestamp with a fresh index.
    """
    return bars.loc[bars["symbol"] == symbol].sort_values("timestamp").reset_index(drop=True)


def load_symbol_bars(
    path: str | Path, symbol: str, timezone: str = DEFAULT_TIMEZONE
) -> pd.DataFrame:
    """Load a CSV file and filter it down to a single symbol's bars.

    Args:
        path: Path to the CSV file (may contain one or many symbols).
        symbol: The ticker symbol to extract.
        timezone: IANA timezone for the loaded bars.

    Returns:
        A DataFrame of only `symbol`'s bars, sorted by timestamp.

    Raises:
        FileNotFoundError: If `path` does not exist.
        ValueError: If the file's schema is invalid or it has no rows.
    """
    return filter_symbol(load_bars_csv(path, timezone=timezone), symbol)


def load_backtest_dataset(
    data_dir: str | Path,
    symbols: list[str],
    confirmation_symbol: str = "QQQ",
    timezone: str = DEFAULT_TIMEZONE,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Load a full local backtest dataset: one or more tradable symbols
    plus the QQQ (or other) confirmation symbol.

    Expects one file per symbol, named "{symbol}_bars.csv", inside
    `data_dir` (this matches the layout used by
    sample_data/backtest/generate_backtest_data.py).

    Args:
        data_dir: Directory containing "{symbol}_bars.csv" files.
        symbols: Tradable symbols to load.
        confirmation_symbol: The directional confirmation symbol
            (e.g. "QQQ"); loaded separately from `symbols`.
        timezone: IANA timezone for all loaded bars.

    Returns:
        (bars_by_symbol, qqq_bars): `bars_by_symbol` maps each tradable
        symbol to its OHLCV DataFrame; `qqq_bars` is the confirmation
        symbol's OHLCV DataFrame.

    Raises:
        FileNotFoundError: If any expected CSV file is missing.
        ValueError: If a file's schema is invalid or it has no rows.
    """
    data_dir = Path(data_dir)

    bars_by_symbol: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        path = data_dir / f"{symbol}_bars.csv"
        bars_by_symbol[symbol] = load_symbol_bars(path, symbol, timezone=timezone)

    qqq_path = data_dir / f"{confirmation_symbol}_bars.csv"
    qqq_bars = load_symbol_bars(qqq_path, confirmation_symbol, timezone=timezone)

    return bars_by_symbol, qqq_bars
