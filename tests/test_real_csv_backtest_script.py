"""
Tests for scripts/run_real_csv_backtest.py.

Uses monkeypatched settings (a small volume lookback) and small,
hand-built synthetic CSV fixtures so the real script's discovery,
validation-gate, backtest, and reporting logic all get exercised end
to end without needing large data files. No network access is
involved anywhere in this file.
"""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import scripts.run_real_csv_backtest as script
from src.journal.trade_journal import TradeJournal

TZ = ZoneInfo("America/New_York")
DAY_A = "2026-09-01"  # history-only: establishes Day B's PDH/PDL
DAY_B = "2026-09-02"


def _row(date_str, time_str, symbol, o, h, l, c, v):
    return {
        "timestamp": f"{date_str} {time_str}",
        "symbol": symbol,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v,
    }


def _demo_rows():
    return [
        _row(DAY_A, "09:30:00", "DEMO", 100.0, 110.0, 90.0, 100.0, 100),  # previous day: PDH=110, PDL=90
        _row(DAY_B, "04:00:00", "DEMO", 100.0, 130.0, 70.0, 100.0, 100),  # premarket: PMH=130, PML=70
        _row(DAY_B, "09:36:00", "DEMO", 95.0, 96.0, 85.0, 95.0, 1000),  # long trigger: sweeps PDL, reclaims
        _row(DAY_B, "09:37:00", "DEMO", 100.0, 124.0, 99.0, 123.6, 500),  # wins the 2.5R target
    ]


def _qqq_rows():
    return [_row(DAY_B, "09:36:00", "QQQ", 500.0, 501.0, 499.5, 501.0, 5000)]


def _write_csv(directory, filename, rows):
    path = directory / filename
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _minimal_settings(tmp_path):
    return {
        "mode": {"trading_mode": "paper", "enable_live_trading": False},
        "session": {
            "timezone": "America/New_York",
            "session_start": "09:35",
            "session_end": "13:00",
            "no_new_trades_after": "12:45",
            "force_flat_time": "13:00",
        },
        "universe_filters": {"min_price": 1.0, "min_market_cap": 1_000_000_000.0},
        "market_levels": {"premarket_start": "04:00", "premarket_end": "09:30"},
        "candle_features": {"volume_lookback_bars": 3, "volume_spike_multiplier": 1.5},
        "strategy": {
            "liquidity_sweep": {
                "min_lower_wick_ratio": 0.5,
                "min_upper_wick_ratio": 0.5,
                "min_volume_multiple": 1.5,
                "reward_risk_targets": [2.5, 3.0],
                "qqq_confirmation": {
                    "long_requires": ["bullish", "neutral"],
                    "short_requires": ["bearish", "neutral"],
                    "neutral_band_pct": 0.05,
                },
            }
        },
        "position_sizing": {"risk_per_trade_pct": 0.333, "max_spread_pct": 0.15, "min_quantity": 1},
        "risk_controls": {"max_trades_per_day": 3, "max_daily_loss_pct": 1.0, "max_consecutive_losses": 2},
        "broker": {"starting_paper_equity": 25_000.0, "commission_per_share": 0.0, "slippage_bps": 0.0},
        "logging": {
            "trade_journal_file": str(tmp_path / "unused.csv"),
            "order_log_file": str(tmp_path / "unused.log"),
        },
    }


@pytest.fixture()
def patched_run(tmp_path, monkeypatch):
    """Redirect settings + output paths into tmp_path so tests never touch the real logs/ dir."""
    monkeypatch.setattr(script, "load_settings", lambda *_a, **_k: _minimal_settings(tmp_path))
    monkeypatch.setattr(script, "REAL_CSV_JOURNAL_PATH", str(tmp_path / "journal.csv"))
    monkeypatch.setattr(script, "REAL_CSV_ORDER_LOG_PATH", str(tmp_path / "orders.log"))
    return tmp_path


def test_discover_tradable_symbols_excludes_confirmation_symbol(tmp_path):
    _write_csv(tmp_path, "DEMO_bars.csv", _demo_rows())
    _write_csv(tmp_path, "QQQ_bars.csv", _qqq_rows())
    _write_csv(tmp_path, "AAPL_bars.csv", _demo_rows())

    symbols = script._discover_tradable_symbols(tmp_path, "QQQ")

    assert symbols == ["AAPL", "DEMO"]


def test_discover_tradable_symbols_empty_directory(tmp_path):
    assert script._discover_tradable_symbols(tmp_path / "missing", "QQQ") == []


def test_best_and_worst_trade():
    trades = [{"pnl": 50.0}, {"pnl": -20.0}, {"pnl": 100.0}]

    best, worst = script._best_and_worst_trade(trades)

    assert best["pnl"] == 100.0
    assert worst["pnl"] == -20.0


def test_best_and_worst_trade_empty_list():
    assert script._best_and_worst_trade([]) == (None, None)


def test_trades_per_symbol_aggregates_count_and_pnl():
    trades = [
        {"symbol": "AAA", "pnl": 10.0},
        {"symbol": "AAA", "pnl": -5.0},
        {"symbol": "BBB", "pnl": 20.0},
    ]

    per_symbol = script._trades_per_symbol(trades)

    assert per_symbol["AAA"] == {"trades": 2, "pnl": 5.0}
    assert per_symbol["BBB"] == {"trades": 1, "pnl": 20.0}


def test_daily_pnl_aggregates_by_calendar_day():
    trades = [
        {"timestamp": "2026-07-01 10:00:00-04:00", "pnl": 10.0},
        {"timestamp": "2026-07-01 11:00:00-04:00", "pnl": 5.0},
        {"timestamp": "2026-07-02 10:00:00-04:00", "pnl": -3.0},
    ]

    per_day = script._daily_pnl(trades)

    assert per_day == {"2026-07-01": 15.0, "2026-07-02": -3.0}


def test_run_real_csv_backtest_end_to_end(tmp_path, patched_run, monkeypatch, capsys):
    _write_csv(tmp_path, "DEMO_bars.csv", _demo_rows())
    _write_csv(tmp_path, "QQQ_bars.csv", _qqq_rows())

    monkeypatch.setattr("sys.argv", ["run_real_csv_backtest.py", "--data-dir", str(tmp_path)])

    script.main()  # should complete without raising SystemExit

    captured = capsys.readouterr()
    assert "REAL CSV HISTORICAL BACKTEST" in captured.out
    assert "Total trades:       1" in captured.out
    assert "Best trade:" in captured.out
    assert "Trades per symbol:" in captured.out
    assert "Daily P&L:" in captured.out

    journal = TradeJournal(str(tmp_path / "journal.csv"))
    journal_df = journal.read_all()
    assert len(journal_df) == 1
    assert journal_df.iloc[0]["pnl"] > 0
    assert journal_df.iloc[0]["reason_exit"] == "target_2.5R"


def test_run_real_csv_backtest_refuses_when_confirmation_symbol_missing(tmp_path, patched_run, monkeypatch, capsys):
    _write_csv(tmp_path, "DEMO_bars.csv", _demo_rows())
    # No QQQ_bars.csv written -- validation must fail.

    monkeypatch.setattr("sys.argv", ["run_real_csv_backtest.py", "--data-dir", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        script.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "VALIDATION FAILED" in captured.err


def test_run_real_csv_backtest_refuses_when_no_tradable_symbols(tmp_path, patched_run, monkeypatch, capsys):
    _write_csv(tmp_path, "QQQ_bars.csv", _qqq_rows())
    # Only the confirmation symbol's file exists -- nothing tradable.

    monkeypatch.setattr("sys.argv", ["run_real_csv_backtest.py", "--data-dir", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        script.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "NO DATA" in captured.err


def test_no_live_broker_class_exists_in_the_real_csv_script_module():
    """Guard test: confirm this script only ever exercises PaperBroker."""
    assert not hasattr(script, "LiveBroker")
