"""Tests for src/journal/trade_journal.py -- CSV-only, no network access."""

from __future__ import annotations

import pytest

from src.journal.trade_journal import REQUIRED_COLUMNS, TradeJournal


def _trade_record(**overrides):
    record = {
        "timestamp": "2026-07-01 09:41:00",
        "entry_time": "2026-07-01 09:40:00",
        "symbol": "DEMO",
        "direction": "long",
        "swept_level": 148.0,
        "swept_level_type": "PDL",
        "entry": 150.0,
        "stop": 148.0,
        "target": "155.0, 156.0",
        "risk_amount": 200.0,
        "quantity": 100,
        "exit": 155.0,
        "pnl": 500.0,
        "r_multiple": 2.5,
        "wick_ratio": 0.6,
        "volume_multiple": 2.0,
        "qqq_confirmation": "bullish",
        "reason_entry": "test entry",
        "reason_exit": "target_2.5R",
    }
    record.update(overrides)
    return record


def test_record_trade_requires_all_new_diagnostic_columns(tmp_path):
    journal = TradeJournal(str(tmp_path / "journal.csv"))
    incomplete = _trade_record()
    del incomplete["r_multiple"]

    with pytest.raises(ValueError, match="r_multiple"):
        journal.record_trade(incomplete)


def test_record_trade_writes_all_required_columns(tmp_path):
    path = tmp_path / "journal.csv"
    journal = TradeJournal(str(path))
    journal.record_trade(_trade_record())

    df = journal.read_all()
    assert len(df) == 1
    for col in REQUIRED_COLUMNS:
        assert col in df.columns


def test_default_journal_appends_across_separate_instances(tmp_path):
    """TradeJournal's own default (overwrite=False) must not destroy
    rows written by a previous instance pointed at the same path."""
    path = str(tmp_path / "journal.csv")

    TradeJournal(path).record_trade(_trade_record(symbol="AAA"))
    TradeJournal(path).record_trade(_trade_record(symbol="BBB"))

    df = TradeJournal(path).read_all()
    assert list(df["symbol"]) == ["AAA", "BBB"]


def test_overwrite_true_clears_existing_file_before_new_run(tmp_path):
    path = str(tmp_path / "journal.csv")

    TradeJournal(path).record_trade(_trade_record(symbol="OLD_RUN"))
    assert len(TradeJournal(path).read_all()) == 1

    fresh = TradeJournal(path, overwrite=True)
    fresh.record_trade(_trade_record(symbol="NEW_RUN"))

    df = TradeJournal(path).read_all()
    assert list(df["symbol"]) == ["NEW_RUN"]


def test_overwrite_true_on_nonexistent_file_does_not_raise(tmp_path):
    path = str(tmp_path / "journal.csv")

    journal = TradeJournal(path, overwrite=True)  # file doesn't exist yet
    journal.record_trade(_trade_record())

    assert len(journal.read_all()) == 1


def test_overwrite_true_with_no_writes_leaves_an_empty_journal(tmp_path):
    """Constructing with overwrite=True and never recording a trade
    must not leave stale rows from a previous run readable."""
    path = str(tmp_path / "journal.csv")
    TradeJournal(path).record_trade(_trade_record())
    assert len(TradeJournal(path).read_all()) == 1

    TradeJournal(path, overwrite=True)  # no record_trade() call this time

    df = TradeJournal(path).read_all()
    assert df.empty
