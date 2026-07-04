"""Tests for src/backtesting/data_validation.py -- local CSV checks only, no network access."""

from __future__ import annotations

import pandas as pd
import pytest

from src.backtesting.data_validation import validate_directory, validate_file


def _write_csv(tmp_path, filename, rows):
    path = tmp_path / filename
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _good_row(ts="2026-07-01 09:30:00", symbol="DEMO", o=100.0, h=101.0, l=99.0, c=100.5, v=1000):
    return {"timestamp": ts, "symbol": symbol, "open": o, "high": h, "low": l, "close": c, "volume": v}


def test_validate_file_passes_on_clean_data(tmp_path):
    path = _write_csv(
        tmp_path,
        "DEMO_bars.csv",
        [
            _good_row("2026-07-01 09:30:00"),
            _good_row("2026-07-01 09:31:00", o=100.5, h=101.5, l=100.0, c=101.0),
        ],
    )

    result = validate_file(path)

    assert result.is_valid
    assert result.errors == []
    assert result.row_count == 2
    assert result.symbols == ["DEMO"]


def test_validate_file_missing_file_reports_error():
    result = validate_file("this/path/does/not/exist_bars.csv")

    assert not result.is_valid
    assert any("not found" in e for e in result.errors)


def test_validate_file_empty_file_reports_error(tmp_path):
    path = tmp_path / "empty.csv"
    pd.DataFrame(columns=["timestamp", "symbol", "open", "high", "low", "close", "volume"]).to_csv(
        path, index=False
    )

    result = validate_file(path)

    assert not result.is_valid
    assert any("no rows" in e for e in result.errors)


def test_validate_file_missing_columns_reports_error(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame([{"timestamp": "2026-07-01 09:30:00", "open": 1}]).to_csv(path, index=False)

    result = validate_file(path)

    assert not result.is_valid
    assert any("missing required columns" in e for e in result.errors)


def test_validate_file_unparseable_timestamp_reports_error(tmp_path):
    path = _write_csv(tmp_path, "bad.csv", [_good_row(ts="not-a-timestamp")])

    result = validate_file(path)

    assert not result.is_valid
    assert any("unparseable timestamp" in e for e in result.errors)


def test_validate_file_missing_symbol_reports_error(tmp_path):
    path = _write_csv(tmp_path, "bad.csv", [_good_row(symbol="")])

    result = validate_file(path)

    assert not result.is_valid
    assert any("missing/empty symbol" in e for e in result.errors)


def test_validate_file_non_numeric_ohlcv_reports_error(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame(
        [{"timestamp": "2026-07-01 09:30:00", "symbol": "DEMO", "open": "abc", "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000}]
    ).to_csv(path, index=False)

    result = validate_file(path)

    assert not result.is_valid
    assert any("column 'open'" in e for e in result.errors)


def test_validate_file_duplicate_timestamp_symbol_reports_error(tmp_path):
    path = _write_csv(
        tmp_path,
        "bad.csv",
        [_good_row("2026-07-01 09:30:00"), _good_row("2026-07-01 09:30:00")],
    )

    result = validate_file(path)

    assert not result.is_valid
    assert any("duplicate (timestamp, symbol)" in e for e in result.errors)


def test_validate_file_high_less_than_low_reports_error(tmp_path):
    path = _write_csv(tmp_path, "bad.csv", [_good_row(h=95.0, l=99.0)])  # high < low

    result = validate_file(path)

    assert not result.is_valid
    assert any("high < low" in e for e in result.errors)


def test_validate_file_high_less_than_open_or_close_reports_error(tmp_path):
    path = _write_csv(tmp_path, "bad.csv", [_good_row(o=100.0, h=99.5, l=95.0, c=99.0)])  # high < open

    result = validate_file(path)

    assert not result.is_valid
    assert any("high < open" in e for e in result.errors)


def test_validate_file_low_greater_than_open_or_close_reports_error(tmp_path):
    path = _write_csv(tmp_path, "bad.csv", [_good_row(o=100.0, h=105.0, l=101.0, c=100.5)])  # low > open, low > close

    result = validate_file(path)

    assert not result.is_valid
    assert any("low > open" in e for e in result.errors)


def test_validate_file_unsorted_timestamps_is_a_warning_not_an_error(tmp_path):
    path = _write_csv(
        tmp_path,
        "unsorted.csv",
        [_good_row("2026-07-01 09:31:00"), _good_row("2026-07-01 09:30:00")],
    )

    result = validate_file(path)

    assert result.is_valid  # a warning must not fail validation
    assert any("not sorted" in w for w in result.warnings)


def test_validate_directory_all_valid_and_confirmation_present(tmp_path):
    _write_csv(tmp_path, "DEMO_bars.csv", [_good_row()])
    _write_csv(tmp_path, "QQQ_bars.csv", [_good_row(symbol="QQQ", o=500, h=501, l=499, c=500.5)])

    result = validate_directory(tmp_path, confirmation_symbol="QQQ")

    assert result.is_valid
    assert result.confirmation_file_found
    assert len(result.files) == 2


def test_validate_directory_missing_confirmation_file_fails(tmp_path):
    _write_csv(tmp_path, "DEMO_bars.csv", [_good_row()])

    result = validate_directory(tmp_path, confirmation_symbol="QQQ")

    assert not result.is_valid
    assert not result.confirmation_file_found
    assert any("confirmation symbol file not found" in e for f in result.files for e in f.errors)


def test_validate_directory_with_no_files_at_all(tmp_path):
    result = validate_directory(tmp_path, confirmation_symbol="QQQ")

    assert not result.is_valid
    assert not result.confirmation_file_found


def test_validate_directory_nonexistent_directory_does_not_raise():
    result = validate_directory("this/directory/does/not/exist", confirmation_symbol="QQQ")

    assert not result.is_valid
    assert result.files  # the missing-confirmation-file entry is still reported


def test_validate_the_committed_example_csv_files_pass():
    """The committed data/examples/*.csv files must themselves pass validation."""
    result = validate_directory("data/examples", confirmation_symbol="QQQ")

    assert result.is_valid, [e for f in result.files for e in f.errors]
    assert result.confirmation_file_found
