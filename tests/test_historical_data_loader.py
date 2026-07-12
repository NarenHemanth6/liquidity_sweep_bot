"""Tests for src/backtesting/data_loader.py -- CSV-only, no network access."""

from __future__ import annotations

import pandas as pd
import pytest

from src.backtesting.data_loader import (
    REQUIRED_COLUMNS,
    filter_symbol,
    load_backtest_dataset,
    load_bars_csv,
    load_symbol_bars,
    resolve_symbol_csv_path,
)


def _write_csv(tmp_path, filename, rows):
    path = tmp_path / filename
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_load_bars_csv_loads_correct_schema_and_dtypes(tmp_path):
    path = _write_csv(
        tmp_path,
        "DEMO_bars.csv",
        [
            {
                "timestamp": "2026-07-01 09:35:00-04:00",
                "symbol": "DEMO",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000,
            },
            {
                "timestamp": "2026-07-01 09:36:00-04:00",
                "symbol": "DEMO",
                "open": 100.5,
                "high": 101.5,
                "low": 100.0,
                "close": 101.0,
                "volume": 1100,
            },
        ],
    )

    df = load_bars_csv(path)

    assert list(REQUIRED_COLUMNS) == ["timestamp", "symbol", "open", "high", "low", "close", "volume"]
    for col in REQUIRED_COLUMNS:
        assert col in df.columns
    assert pd.api.types.is_datetime64_any_dtype(df["timestamp"])
    assert df["timestamp"].dt.tz is not None
    assert df["open"].dtype == float
    assert len(df) == 2


def test_load_bars_csv_sorts_ascending_by_timestamp(tmp_path):
    path = _write_csv(
        tmp_path,
        "DEMO_bars.csv",
        [
            {"timestamp": "2026-07-01 09:36:00", "symbol": "DEMO", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"timestamp": "2026-07-01 09:35:00", "symbol": "DEMO", "open": 2, "high": 2, "low": 2, "close": 2, "volume": 2},
        ],
    )

    df = load_bars_csv(path)

    assert df["timestamp"].is_monotonic_increasing
    assert df.iloc[0]["open"] == 2  # the 09:35 row, now first


def test_load_bars_csv_localizes_naive_timestamps_to_requested_timezone(tmp_path):
    path = _write_csv(
        tmp_path,
        "DEMO_bars.csv",
        [{"timestamp": "2026-07-01 09:35:00", "symbol": "DEMO", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
    )

    df = load_bars_csv(path, timezone="America/New_York")

    assert str(df["timestamp"].iloc[0].tzinfo) is not None
    assert df["timestamp"].iloc[0].hour == 9


def test_load_bars_csv_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_bars_csv("this/path/does/not/exist_bars.csv")


def test_load_bars_csv_missing_columns_raises(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame([{"timestamp": "2026-07-01 09:35:00", "open": 1}]).to_csv(path, index=False)

    with pytest.raises(ValueError, match="missing required columns"):
        load_bars_csv(path)


def test_load_bars_csv_empty_file_raises(tmp_path):
    path = tmp_path / "empty.csv"
    pd.DataFrame(columns=list(REQUIRED_COLUMNS)).to_csv(path, index=False)

    with pytest.raises(ValueError, match="no rows"):
        load_bars_csv(path)


def test_filter_symbol_keeps_only_requested_symbol(tmp_path):
    path = _write_csv(
        tmp_path,
        "multi_bars.csv",
        [
            {"timestamp": "2026-07-01 09:35:00", "symbol": "DEMO", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"timestamp": "2026-07-01 09:35:00", "symbol": "QQQ", "open": 500, "high": 500, "low": 500, "close": 500, "volume": 1},
        ],
    )
    df = load_bars_csv(path)

    demo_only = filter_symbol(df, "DEMO")
    qqq_only = filter_symbol(df, "QQQ")

    assert set(demo_only["symbol"]) == {"DEMO"}
    assert set(qqq_only["symbol"]) == {"QQQ"}
    assert len(demo_only) == 1
    assert len(qqq_only) == 1


def test_load_symbol_bars_filters_a_multi_symbol_file(tmp_path):
    path = _write_csv(
        tmp_path,
        "multi_bars.csv",
        [
            {"timestamp": "2026-07-01 09:35:00", "symbol": "DEMO", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"timestamp": "2026-07-01 09:35:00", "symbol": "QQQ", "open": 500, "high": 500, "low": 500, "close": 500, "volume": 1},
            {"timestamp": "2026-07-01 09:36:00", "symbol": "DEMO", "open": 2, "high": 2, "low": 2, "close": 2, "volume": 2},
        ],
    )

    demo_bars = load_symbol_bars(path, "DEMO")

    assert len(demo_bars) == 2
    assert set(demo_bars["symbol"]) == {"DEMO"}


def test_load_backtest_dataset_loads_one_or_multiple_symbols(tmp_path):
    _write_csv(
        tmp_path,
        "AAA_bars.csv",
        [{"timestamp": "2026-07-01 09:35:00", "symbol": "AAA", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
    )
    _write_csv(
        tmp_path,
        "BBB_bars.csv",
        [{"timestamp": "2026-07-01 09:35:00", "symbol": "BBB", "open": 2, "high": 2, "low": 2, "close": 2, "volume": 2}],
    )
    _write_csv(
        tmp_path,
        "QQQ_bars.csv",
        [{"timestamp": "2026-07-01 09:35:00", "symbol": "QQQ", "open": 500, "high": 500, "low": 500, "close": 500, "volume": 5}],
    )

    bars_by_symbol, qqq_bars = load_backtest_dataset(tmp_path, symbols=["AAA", "BBB"], confirmation_symbol="QQQ")

    assert set(bars_by_symbol.keys()) == {"AAA", "BBB"}
    assert set(bars_by_symbol["AAA"]["symbol"]) == {"AAA"}
    assert set(bars_by_symbol["BBB"]["symbol"]) == {"BBB"}
    assert set(qqq_bars["symbol"]) == {"QQQ"}


def test_load_backtest_dataset_missing_symbol_file_raises(tmp_path):
    _write_csv(
        tmp_path,
        "QQQ_bars.csv",
        [{"timestamp": "2026-07-01 09:35:00", "symbol": "QQQ", "open": 500, "high": 500, "low": 500, "close": 500, "volume": 5}],
    )

    with pytest.raises(FileNotFoundError):
        load_backtest_dataset(tmp_path, symbols=["MISSING"], confirmation_symbol="QQQ")


def test_resolve_symbol_csv_path_finds_bars_suffix(tmp_path):
    path = _write_csv(
        tmp_path,
        "NVDA_bars.csv",
        [{"timestamp": "2026-07-01 09:35:00", "symbol": "NVDA", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
    )

    assert resolve_symbol_csv_path(tmp_path, "NVDA") == path


def test_resolve_symbol_csv_path_finds_1min_suffix_with_no_rename(tmp_path):
    """scripts/download_ibkr_bars.py writes '{symbol}_1min.csv' -- this must
    resolve directly, with no rename to '{symbol}_bars.csv' required."""
    path = _write_csv(
        tmp_path,
        "NVDA_1min.csv",
        [{"timestamp": "2026-07-01 09:35:00", "symbol": "NVDA", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
    )

    assert resolve_symbol_csv_path(tmp_path, "NVDA") == path


def test_resolve_symbol_csv_path_prefers_bars_suffix_when_both_exist(tmp_path):
    bars_path = _write_csv(
        tmp_path,
        "NVDA_bars.csv",
        [{"timestamp": "2026-07-01 09:35:00", "symbol": "NVDA", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
    )
    _write_csv(
        tmp_path,
        "NVDA_1min.csv",
        [{"timestamp": "2026-07-01 09:35:00", "symbol": "NVDA", "open": 2, "high": 2, "low": 2, "close": 2, "volume": 2}],
    )

    assert resolve_symbol_csv_path(tmp_path, "NVDA") == bars_path


def test_resolve_symbol_csv_path_raises_when_no_candidate_exists(tmp_path):
    with pytest.raises(FileNotFoundError, match="NVDA_bars.csv"):
        resolve_symbol_csv_path(tmp_path, "NVDA")


def test_load_backtest_dataset_loads_1min_suffixed_files_directly(tmp_path):
    """The exact IBKR-download workflow: {symbol}_1min.csv files load
    with no rename to {symbol}_bars.csv."""
    _write_csv(
        tmp_path,
        "QQQ_1min.csv",
        [{"timestamp": "2026-07-01 09:35:00", "symbol": "QQQ", "open": 500, "high": 500, "low": 500, "close": 500, "volume": 5}],
    )
    _write_csv(
        tmp_path,
        "NVDA_1min.csv",
        [{"timestamp": "2026-07-01 09:35:00", "symbol": "NVDA", "open": 100, "high": 100, "low": 100, "close": 100, "volume": 10}],
    )

    bars_by_symbol, qqq_bars = load_backtest_dataset(tmp_path, symbols=["NVDA"], confirmation_symbol="QQQ")

    assert set(bars_by_symbol["NVDA"]["symbol"]) == {"NVDA"}
    assert set(qqq_bars["symbol"]) == {"QQQ"}


def test_load_sample_backtest_csv_files_from_disk():
    """The committed sample_data/backtest/*.csv files load correctly."""
    bars_by_symbol, qqq_bars = load_backtest_dataset(
        "sample_data/backtest", symbols=["DEMO"], confirmation_symbol="QQQ"
    )

    assert not bars_by_symbol["DEMO"].empty
    assert not qqq_bars.empty
    for col in REQUIRED_COLUMNS:
        assert col in bars_by_symbol["DEMO"].columns
        assert col in qqq_bars.columns

    dates = bars_by_symbol["DEMO"]["timestamp"].dt.date.unique()
    assert len(dates) >= 2  # at least 2 trading days, per project requirements
