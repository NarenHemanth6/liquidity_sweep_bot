"""Tests for src/risk/risk_controls.py — daily loss limit & time cutoffs"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.risk.risk_controls import RiskManager

ET = ZoneInfo("America/New_York")

CFG = {
    "max_trades_per_day": 3,
    "max_daily_loss_pct": 1.0,
    "max_consecutive_losses": 2,
    "no_new_trades_after": "12:45",
    "force_flat_time": "13:00",
    "timezone": "America/New_York",
}


def make_time(hour: int, minute: int) -> datetime:
    return datetime(2026, 7, 1, hour, minute, tzinfo=ET)


def test_can_open_new_trade_allows_when_fresh():
    rm = RiskManager(CFG, starting_equity=25_000.0)
    allowed, reason = rm.can_open_new_trade(make_time(10, 0))
    assert allowed is True
    assert reason == "ok"


def test_blocks_after_daily_loss_limit_breached():
    rm = RiskManager(CFG, starting_equity=25_000.0)
    # 1% of 25,000 = $250 max daily loss
    rm.register_trade_result(-260.0)
    allowed, reason = rm.can_open_new_trade(make_time(10, 30))
    assert allowed is False
    assert "daily loss" in reason
    assert rm.state.halted is True


def test_does_not_block_when_loss_below_limit():
    rm = RiskManager(CFG, starting_equity=25_000.0)
    rm.register_trade_result(-100.0)  # below $250 limit
    allowed, _ = rm.can_open_new_trade(make_time(10, 30))
    assert allowed is True


def test_blocks_after_two_consecutive_losses():
    rm = RiskManager(CFG, starting_equity=25_000.0)
    rm.register_trade_result(-10.0)
    rm.register_trade_result(-10.0)
    allowed, reason = rm.can_open_new_trade(make_time(10, 30))
    assert allowed is False
    assert "consecutive losses" in reason


def test_winning_trade_resets_consecutive_loss_counter():
    rm = RiskManager(CFG, starting_equity=25_000.0)
    rm.register_trade_result(-10.0)
    rm.register_trade_result(50.0)  # win resets streak
    assert rm.state.consecutive_losses == 0
    allowed, _ = rm.can_open_new_trade(make_time(10, 30))
    assert allowed is True


def test_blocks_new_trades_after_1245_et():
    rm = RiskManager(CFG, starting_equity=25_000.0)
    allowed, reason = rm.can_open_new_trade(make_time(12, 46))
    assert allowed is False
    assert "no new trades" in reason.lower()


def test_allows_new_trade_exactly_before_cutoff():
    rm = RiskManager(CFG, starting_equity=25_000.0)
    allowed, _ = rm.can_open_new_trade(make_time(12, 44))
    assert allowed is True


def test_should_force_flat_true_at_and_after_1pm():
    rm = RiskManager(CFG, starting_equity=25_000.0)
    assert rm.should_force_flat(make_time(13, 0)) is True
    assert rm.should_force_flat(make_time(13, 30)) is True


def test_should_force_flat_false_before_1pm():
    rm = RiskManager(CFG, starting_equity=25_000.0)
    assert rm.should_force_flat(make_time(12, 59)) is False


def test_reset_for_new_day_clears_state():
    rm = RiskManager(CFG, starting_equity=25_000.0)
    rm.register_trade_result(-260.0)
    assert rm.state.halted is True

    rm.reset_for_new_day(starting_equity=24_740.0)
    assert rm.state.halted is False
    assert rm.state.trades_taken == 0
    assert rm.state.consecutive_losses == 0
    assert rm.state.realized_pnl == 0.0
    assert rm.state.starting_equity == 24_740.0
