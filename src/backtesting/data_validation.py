"""
backtesting/data_validation.py

Validates local historical OHLCV minute-bar CSV files before they are
used for backtesting. This module only ever reads local files with
pandas -- no network access, no broker connection, and no credentials
of any kind are involved anywhere in this file.

Checks performed on each file:
    - required columns are present (timestamp, symbol, open, high,
      low, close, volume)
    - every timestamp parses
    - every symbol value is present (non-empty)
    - open/high/low/close/volume are all numeric
    - no duplicate (timestamp, symbol) rows
    - high >= low
    - high >= open and high >= close
    - low <= open and low <= close
    - rows are sorted ascending by timestamp (warning only -- the data
      loader sorts automatically, so this is advisory, not fatal)

`validate_directory()` additionally checks that a file for the
confirmation symbol (default "QQQ") exists in the directory, since the
strategy always requires it for directional confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = ("timestamp", "symbol", "open", "high", "low", "close", "volume")
NUMERIC_COLUMNS = ("open", "high", "low", "close", "volume")


@dataclass
class FileValidationResult:
    """Validation outcome for a single CSV file.

    Attributes:
        path: Path to the file that was validated.
        row_count: Number of data rows read (0 if unreadable/empty).
        symbols: Distinct symbol values found in the file.
        errors: Problems that make the file unsafe to backtest with.
        warnings: Non-fatal issues worth surfacing to the user.
    """

    path: str
    row_count: int = 0
    symbols: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """True if this file has no errors (warnings are still allowed)."""
        return not self.errors


def validate_file(path: str | Path) -> FileValidationResult:
    """Validate one historical OHLCV CSV file.

    Never raises for a malformed file -- every failure is reported in
    the returned result's `errors` list instead, so callers can
    validate a whole directory without a single bad file aborting the
    run.

    Args:
        path: Path to the CSV file.

    Returns:
        A FileValidationResult describing every error/warning found.
    """
    path = Path(path)
    result = FileValidationResult(path=str(path))

    if not path.exists():
        result.errors.append(f"file not found: {path}")
        return result

    try:
        df = pd.read_csv(path)
    except Exception as exc:  # pragma: no cover - pandas raises many exception types
        result.errors.append(f"could not read CSV: {exc}")
        return result

    if df.empty:
        result.errors.append("file contains no rows")
        return result

    result.row_count = len(df)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        result.errors.append(f"missing required columns: {missing}")
        return result  # every remaining check depends on these columns

    result.symbols = sorted(str(s) for s in df["symbol"].dropna().unique())

    parsed_ts = pd.to_datetime(df["timestamp"], errors="coerce")
    bad_ts_count = int(parsed_ts.isna().sum())
    if bad_ts_count:
        result.errors.append(f"{bad_ts_count} row(s) have an unparseable timestamp")

    missing_symbol_mask = df["symbol"].isna() | (df["symbol"].astype(str).str.strip() == "")
    missing_symbol_count = int(missing_symbol_mask.sum())
    if missing_symbol_count:
        result.errors.append(f"{missing_symbol_count} row(s) have a missing/empty symbol")

    numeric = pd.DataFrame({col: pd.to_numeric(df[col], errors="coerce") for col in NUMERIC_COLUMNS})
    for col in NUMERIC_COLUMNS:
        bad_count = int(numeric[col].isna().sum())
        if bad_count:
            result.errors.append(f"column '{col}' has {bad_count} non-numeric or missing value(s)")

    dedup_key = pd.DataFrame({"timestamp": parsed_ts, "symbol": df["symbol"]})
    dup_count = int(dedup_key.duplicated(keep=False).sum())
    if dup_count:
        result.errors.append(f"{dup_count} row(s) share a duplicate (timestamp, symbol) pair")

    valid_ohlc_mask = numeric[["open", "high", "low", "close"]].notna().all(axis=1)
    ohlc = numeric.loc[valid_ohlc_mask]

    bad_high_low = int((ohlc["high"] < ohlc["low"]).sum())
    if bad_high_low:
        result.errors.append(f"{bad_high_low} row(s) have high < low")

    bad_high = int(((ohlc["high"] < ohlc["open"]) | (ohlc["high"] < ohlc["close"])).sum())
    if bad_high:
        result.errors.append(f"{bad_high} row(s) have high < open or high < close")

    bad_low = int(((ohlc["low"] > ohlc["open"]) | (ohlc["low"] > ohlc["close"])).sum())
    if bad_low:
        result.errors.append(f"{bad_low} row(s) have low > open or low > close")

    valid_ts = parsed_ts.dropna()
    if not valid_ts.is_monotonic_increasing:
        result.warnings.append(
            "rows are not sorted ascending by timestamp "
            "(the data loader sorts automatically, but fix this at the source if possible)"
        )

    return result


@dataclass
class DirectoryValidationResult:
    """Validation outcome for an entire data directory.

    Attributes:
        directory: The directory that was scanned.
        files: One FileValidationResult per "*_bars.csv" file found,
            plus a synthetic entry for a missing confirmation-symbol
            file (if applicable).
        confirmation_symbol: The confirmation symbol required
            (e.g. "QQQ").
        confirmation_file_found: Whether a file for the confirmation
            symbol was found in the directory.
    """

    directory: str
    files: list[FileValidationResult] = field(default_factory=list)
    confirmation_symbol: str = "QQQ"
    confirmation_file_found: bool = False

    @property
    def is_valid(self) -> bool:
        """True if every file is valid AND the confirmation file was found."""
        return self.confirmation_file_found and all(f.is_valid for f in self.files)


def validate_directory(
    data_dir: str | Path,
    confirmation_symbol: str = "QQQ",
    pattern: str = "*_bars.csv",
) -> DirectoryValidationResult:
    """Validate every historical OHLCV CSV file in a directory.

    Args:
        data_dir: Directory to scan for CSV files.
        confirmation_symbol: The directional confirmation symbol whose
            file (e.g. "QQQ_bars.csv") must be present.
        pattern: Glob pattern used to find CSV files in `data_dir`.

    Returns:
        A DirectoryValidationResult covering every matched file plus
        the confirmation-file presence check. If `data_dir` doesn't
        exist, `files` is empty and `confirmation_file_found` is False
        (never raises).
    """
    data_dir = Path(data_dir)
    result = DirectoryValidationResult(directory=str(data_dir), confirmation_symbol=confirmation_symbol)

    paths = sorted(data_dir.glob(pattern)) if data_dir.exists() else []
    for path in paths:
        result.files.append(validate_file(path))

    confirmation_path = data_dir / f"{confirmation_symbol}_bars.csv"
    result.confirmation_file_found = confirmation_path.exists()
    if not result.confirmation_file_found:
        missing = FileValidationResult(path=str(confirmation_path))
        missing.errors.append(
            f"confirmation symbol file not found: {confirmation_path.name} "
            f"(required for directional confirmation)"
        )
        result.files.append(missing)

    return result
