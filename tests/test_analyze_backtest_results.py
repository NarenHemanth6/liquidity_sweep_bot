"""
Tests for scripts/analyze_backtest_results.py.

All diagnostic-calculation tests use a small, hand-built journal
DataFrame with known, hand-computed expected results (see the
docstring on FIXTURE_TRADES below). load_journal()/CSV round-trip
tests use tmp_path only -- no network access anywhere in this file.
"""

from __future__ import annotations

import pandas as pd
import pytest

import scripts.analyze_backtest_results as script
from src.journal.trade_journal import TradeJournal

# Five hand-built trades with known outcomes, used to hand-verify every
# aggregation below:
#
#   #1  2026-07-01 09:40  AAPL long   pnl=+200  risk=100 -> r=+2.0  PML  bullish  wick=0.60 vol=2.0  target_2.5R
#   #2  2026-07-01 10:15  AAPL short  pnl=-80   risk=100 -> r=-0.8  PDH  bearish  wick=0.55 vol=1.8  stop
#   #3  2026-07-02 09:50  MSFT long   pnl=-90   risk=90  -> r=-1.0  PDL  neutral  wick=0.52 vol=1.6  stop
#   #4  2026-07-02 11:05  MSFT long   pnl=-85   risk=85  -> r=-1.0  PML  bullish  wick=0.58 vol=2.1  stop
#   #5  2026-07-03 09:45  AAPL short  pnl=+150  risk=75  -> r=+2.0  PMH  bearish  wick=0.65 vol=2.5  target_2.5R
FIXTURE_TRADES = [
    {
        "timestamp": "2026-07-01 09:41:00",
        "entry_time": "2026-07-01 09:40:00",
        "symbol": "AAPL",
        "direction": "long",
        "swept_level": 148.0,
        "swept_level_type": "PML",
        "entry": 150.0,
        "stop": 148.0,
        "target": "155.0",
        "risk_amount": 100.0,
        "quantity": 50,
        "exit": 155.0,
        "pnl": 200.0,
        "r_multiple": 2.0,
        "wick_ratio": 0.60,
        "volume_multiple": 2.0,
        "qqq_confirmation": "bullish",
        "reason_entry": "e1",
        "reason_exit": "target_2.5R",
    },
    {
        "timestamp": "2026-07-01 10:16:00",
        "entry_time": "2026-07-01 10:15:00",
        "symbol": "AAPL",
        "direction": "short",
        "swept_level": 300.0,
        "swept_level_type": "PDH",
        "entry": 298.0,
        "stop": 300.0,
        "target": "293.0",
        "risk_amount": 100.0,
        "quantity": 50,
        "exit": 299.6,
        "pnl": -80.0,
        "r_multiple": -0.8,
        "wick_ratio": 0.55,
        "volume_multiple": 1.8,
        "qqq_confirmation": "bearish",
        "reason_entry": "e2",
        "reason_exit": "stop",
    },
    {
        "timestamp": "2026-07-02 09:51:00",
        "entry_time": "2026-07-02 09:50:00",
        "symbol": "MSFT",
        "direction": "long",
        "swept_level": 400.0,
        "swept_level_type": "PDL",
        "entry": 402.0,
        "stop": 400.0,
        "target": "407.0",
        "risk_amount": 90.0,
        "quantity": 45,
        "exit": 400.0,
        "pnl": -90.0,
        "r_multiple": -1.0,
        "wick_ratio": 0.52,
        "volume_multiple": 1.6,
        "qqq_confirmation": "neutral",
        "reason_entry": "e3",
        "reason_exit": "stop",
    },
    {
        "timestamp": "2026-07-02 11:06:00",
        "entry_time": "2026-07-02 11:05:00",
        "symbol": "MSFT",
        "direction": "long",
        "swept_level": 371.0,
        "swept_level_type": "PML",
        "entry": 373.0,
        "stop": 371.0,
        "target": "378.0",
        "risk_amount": 85.0,
        "quantity": 42.5,
        "exit": 371.0,
        "pnl": -85.0,
        "r_multiple": -1.0,
        "wick_ratio": 0.58,
        "volume_multiple": 2.1,
        "qqq_confirmation": "bullish",
        "reason_entry": "e4",
        "reason_exit": "stop",
    },
    {
        "timestamp": "2026-07-03 09:46:00",
        "entry_time": "2026-07-03 09:45:00",
        "symbol": "AAPL",
        "direction": "short",
        "swept_level": 296.0,
        "swept_level_type": "PMH",
        "entry": 294.0,
        "stop": 296.0,
        "target": "289.0",
        "risk_amount": 75.0,
        "quantity": 37.5,
        "exit": 289.0,
        "pnl": 150.0,
        "r_multiple": 2.0,
        "wick_ratio": 0.65,
        "volume_multiple": 2.5,
        "qqq_confirmation": "bearish",
        "reason_entry": "e5",
        "reason_exit": "target_2.5R",
    },
]


@pytest.fixture()
def df():
    frame = pd.DataFrame(FIXTURE_TRADES)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame["entry_time"] = pd.to_datetime(frame["entry_time"])
    return frame


@pytest.fixture()
def empty_df():
    return pd.DataFrame(columns=list(pd.DataFrame(FIXTURE_TRADES).columns))


# --- load_journal (CSV round-trip) --------------------------------------


def test_load_journal_missing_file_returns_empty_frame(tmp_path):
    result = script.load_journal(str(tmp_path / "does_not_exist.csv"))
    assert result.empty


def test_load_journal_round_trips_through_trade_journal(tmp_path):
    path = str(tmp_path / "journal.csv")
    journal = TradeJournal(path)
    for trade in FIXTURE_TRADES:
        journal.record_trade(trade)

    result = script.load_journal(path)

    assert len(result) == 5
    assert pd.api.types.is_datetime64_any_dtype(result["timestamp"])
    assert pd.api.types.is_datetime64_any_dtype(result["entry_time"])


# --- R-multiple calculations ---------------------------------------------


def test_compute_r_multiple_positive_pnl():
    assert script.compute_r_multiple(pnl=200.0, risk_amount=100.0) == pytest.approx(2.0)


def test_compute_r_multiple_negative_pnl():
    assert script.compute_r_multiple(pnl=-80.0, risk_amount=100.0) == pytest.approx(-0.8)


def test_compute_r_multiple_zero_risk_amount_returns_zero():
    assert script.compute_r_multiple(pnl=50.0, risk_amount=0.0) == 0.0


def test_compute_r_multiple_negative_risk_amount_returns_zero():
    assert script.compute_r_multiple(pnl=50.0, risk_amount=-10.0) == 0.0


def test_with_r_multiple_matches_hand_computed_values(df):
    result = script.with_r_multiple(df)
    assert list(result["r_multiple"]) == pytest.approx([2.0, -0.8, -1.0, -1.0, 2.0])


def test_average_r_multiple(df):
    # (2.0 - 0.8 - 1.0 - 1.0 + 2.0) / 5 == 0.24
    assert script.average_r_multiple(df) == pytest.approx(0.24)


def test_average_r_multiple_empty(empty_df):
    assert script.average_r_multiple(empty_df) == 0.0


# --- trades by date / symbol / direction ----------------------------------


def test_trades_by_date(df):
    result = script.trades_by_date(df).set_index("date")
    assert result.loc[pd.Timestamp("2026-07-01").date(), "trades"] == 2
    assert result.loc[pd.Timestamp("2026-07-01").date(), "pnl"] == pytest.approx(120.0)
    assert result.loc[pd.Timestamp("2026-07-02").date(), "trades"] == 2
    assert result.loc[pd.Timestamp("2026-07-02").date(), "pnl"] == pytest.approx(-175.0)
    assert result.loc[pd.Timestamp("2026-07-03").date(), "trades"] == 1
    assert result.loc[pd.Timestamp("2026-07-03").date(), "pnl"] == pytest.approx(150.0)


def test_trades_by_symbol(df):
    result = script.trades_by_symbol(df).set_index("symbol")
    assert result.loc["AAPL", "trades"] == 3
    assert result.loc["AAPL", "pnl"] == pytest.approx(270.0)
    assert result.loc["MSFT", "trades"] == 2
    assert result.loc["MSFT", "pnl"] == pytest.approx(-175.0)


def test_trades_by_direction(df):
    result = script.trades_by_direction(df).set_index("direction")
    assert result.loc["long", "trades"] == 3
    assert result.loc["long", "pnl"] == pytest.approx(25.0)
    assert result.loc["short", "trades"] == 2
    assert result.loc["short", "pnl"] == pytest.approx(70.0)


# --- win/loss by symbol and direction -------------------------------------


def test_win_loss_by_symbol(df):
    result = script.win_loss_by_symbol(df).set_index("symbol")
    assert result.loc["AAPL", "wins"] == 2
    assert result.loc["AAPL", "losses"] == 1
    assert result.loc["AAPL", "win_rate"] == pytest.approx(2 / 3)
    assert result.loc["MSFT", "wins"] == 0
    assert result.loc["MSFT", "losses"] == 2
    assert result.loc["MSFT", "win_rate"] == 0.0


def test_win_loss_by_direction(df):
    result = script.win_loss_by_direction(df).set_index("direction")
    assert result.loc["long", "wins"] == 1
    assert result.loc["long", "losses"] == 2
    assert result.loc["short", "wins"] == 1
    assert result.loc["short", "losses"] == 1


def test_win_loss_by_symbol_empty(empty_df):
    assert script.win_loss_by_symbol(empty_df).empty


# --- average/largest win/loss ---------------------------------------------


def test_average_win(df):
    assert script.average_win(df) == pytest.approx((200.0 + 150.0) / 2)


def test_average_loss(df):
    assert script.average_loss(df) == pytest.approx((-80.0 - 90.0 - 85.0) / 3)


def test_average_win_no_wins(empty_df):
    assert script.average_win(empty_df) == 0.0


def test_largest_win(df):
    win = script.largest_win(df)
    assert win["symbol"] == "AAPL"
    assert win["pnl"] == pytest.approx(200.0)


def test_largest_loss(df):
    loss = script.largest_loss(df)
    assert loss["symbol"] == "MSFT"
    assert loss["pnl"] == pytest.approx(-90.0)


def test_largest_win_none_when_no_trades(empty_df):
    assert script.largest_win(empty_df) is None


def test_largest_loss_none_when_no_losses():
    all_wins = pd.DataFrame([FIXTURE_TRADES[0], FIXTURE_TRADES[4]])
    all_wins["entry_time"] = pd.to_datetime(all_wins["entry_time"])
    assert script.largest_loss(all_wins) is None


# --- consecutive losses ---------------------------------------------------


def test_max_consecutive_losses(df):
    # Chronological order: win, loss, loss, loss, win -> streak of 3.
    assert script.max_consecutive_losses(df) == 3


def test_max_consecutive_losses_no_losses():
    all_wins = pd.DataFrame([FIXTURE_TRADES[0], FIXTURE_TRADES[4]])
    all_wins["entry_time"] = pd.to_datetime(all_wins["entry_time"])
    assert script.max_consecutive_losses(all_wins) == 0


def test_max_consecutive_losses_empty(empty_df):
    assert script.max_consecutive_losses(empty_df) == 0


# --- time of day / level swept / QQQ confirmation -------------------------


def test_time_of_day_performance(df):
    result = script.time_of_day_performance(df).set_index("hour")
    assert result.loc["09:00", "trades"] == 3  # trades 1, 3, 5
    assert result.loc["09:00", "wins"] == 2
    assert result.loc["09:00", "pnl"] == pytest.approx(200.0 - 90.0 + 150.0)
    assert result.loc["10:00", "trades"] == 1
    assert result.loc["11:00", "trades"] == 1


def test_level_swept_performance(df):
    result = script.level_swept_performance(df).set_index("swept_level_type")
    assert result.loc["PML", "trades"] == 2  # trades 1, 4
    assert result.loc["PML", "wins"] == 1
    assert result.loc["PML", "pnl"] == pytest.approx(200.0 - 85.0)
    assert result.loc["PDH", "trades"] == 1
    assert result.loc["PDL", "trades"] == 1
    assert result.loc["PMH", "trades"] == 1
    assert result.loc["PMH", "wins"] == 1


def test_qqq_confirmation_performance(df):
    result = script.qqq_confirmation_performance(df).set_index("qqq_confirmation")
    assert result.loc["bullish", "trades"] == 2
    assert result.loc["bullish", "pnl"] == pytest.approx(200.0 - 85.0)
    assert result.loc["bearish", "trades"] == 2
    assert result.loc["bearish", "pnl"] == pytest.approx(-80.0 + 150.0)
    assert result.loc["neutral", "trades"] == 1
    assert result.loc["neutral", "wins"] == 0


# --- wick ratio / volume multiple stats -----------------------------------


def test_wick_ratio_stats(df):
    stats = script.wick_ratio_stats(df)
    assert stats["overall"] == pytest.approx((0.60 + 0.55 + 0.52 + 0.58 + 0.65) / 5)
    assert stats["wins"] == pytest.approx((0.60 + 0.65) / 2)
    assert stats["losses"] == pytest.approx((0.55 + 0.52 + 0.58) / 3)


def test_volume_multiple_stats(df):
    stats = script.volume_multiple_stats(df)
    assert stats["overall"] == pytest.approx((2.0 + 1.8 + 1.6 + 2.1 + 2.5) / 5)
    assert stats["wins"] == pytest.approx((2.0 + 2.5) / 2)
    assert stats["losses"] == pytest.approx((1.8 + 1.6 + 2.1) / 3)


def test_wick_ratio_stats_empty(empty_df):
    stats = script.wick_ratio_stats(empty_df)
    assert stats == {"overall": 0.0, "wins": 0.0, "losses": 0.0}


# --- exit reason / stop-out count ------------------------------------------


def test_exit_reason_breakdown(df):
    breakdown = script.exit_reason_breakdown(df)
    assert breakdown == {"stop": 3, "target_2.5R": 2}


def test_stop_out_count(df):
    assert script.stop_out_count(df) == 3


def test_stop_out_count_empty(empty_df):
    assert script.stop_out_count(empty_df) == 0


# --- main() end-to-end ------------------------------------------------


def test_main_reads_journal_path_argument_and_prints_report(tmp_path, monkeypatch, capsys):
    path = tmp_path / "journal.csv"
    journal = TradeJournal(str(path))
    for trade in FIXTURE_TRADES:
        journal.record_trade(trade)

    monkeypatch.setattr("sys.argv", ["analyze_backtest_results.py", "--journal-path", str(path)])

    script.main()

    captured = capsys.readouterr()
    assert "BACKTEST DIAGNOSTIC REPORT" in captured.out
    assert "Total trades: 5" in captured.out


def test_main_missing_journal_file_reports_no_trades(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv", ["analyze_backtest_results.py", "--journal-path", str(tmp_path / "missing.csv")]
    )

    script.main()

    captured = capsys.readouterr()
    assert "No trades found" in captured.out


# --- print_report smoke tests ---------------------------------------------


def test_print_report_empty_journal_does_not_raise(empty_df, capsys):
    script.print_report(empty_df)
    captured = capsys.readouterr()
    assert "No trades found" in captured.out


def test_print_report_populated_journal_includes_all_sections(df, capsys):
    script.print_report(df)
    captured = capsys.readouterr()
    for expected in (
        "Trades by date:",
        "Trades by symbol:",
        "Trades by direction:",
        "Win/loss by symbol:",
        "Win/loss by direction:",
        "Max consecutive losses: 3",
        "Time of day performance",
        "Level swept performance",
        "QQQ confirmation value at entry:",
        "Wick ratio at entry:",
        "Volume spike at entry",
        "Average R-multiple:",
        "R-multiple per trade:",
        "Exit reason breakdown:",
        "Stop-outs:          3",
        "Reached 2.5R target: 2",
        "Reached 3R target:   0",
    ):
        assert expected in captured.out
