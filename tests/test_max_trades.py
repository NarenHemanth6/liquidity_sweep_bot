"""Tests for src/risk/risk_controls.py — max trades per day"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.risk.risk_controls import RiskManager

ET = ZoneInfo("America/New_York")

CFG = {
    "max_trades_per_day": 3,
    "max_daily_loss_pct": 1.0,
    "max_consecutive_losses": 5,  # high, so it doesn't interfere with this test
    "no_new_trades_after": "12:45",
    "force_flat_time": "13:00",
    "timezone": "America/New_York",
}

NOW = datetime(2026, 7, 1, 10, 0, tzinfo=ET)


def test_allows_first_three_trades():
    rm = RiskManager(CFG, starting_equity=25_000.0)
    for _ in range(3):
        allowed, reason = rm.can_open_new_trade(NOW)
        assert allowed is True
        assert reason == "ok"
        # Simulate a small win each time so we isolate the trade-count limit
        rm.register_trade_result(10.0)


def test_blocks_fourth_trade_attempt():
    rm = RiskManager(CFG, starting_equity=25_000.0)
    for _ in range(3):
        rm.register_trade_result(10.0)

    allowed, reason = rm.can_open_new_trade(NOW)
    assert allowed is False
    assert "max trades per day" in reason


def test_rejected_signals_do_not_count_toward_trade_limit():
    rm = RiskManager(CFG, starting_equity=25_000.0)
    # can_open_new_trade being called repeatedly (e.g. signals that never
    # get filled) must not itself increment trades_taken.
    for _ in range(10):
        rm.can_open_new_trade(NOW)
    assert rm.state.trades_taken == 0

    allowed, _ = rm.can_open_new_trade(NOW)
    assert allowed is True
