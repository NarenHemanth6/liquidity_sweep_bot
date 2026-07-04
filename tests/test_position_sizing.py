"""Tests for src/risk/position_sizing.py"""

from __future__ import annotations

import pytest

from src.risk.position_sizing import calculate_position_size, check_spread


def test_calculate_position_size_normal_case():
    # $25,000 equity, 0.333% risk = $83.25 dollar risk, $1 stop distance
    result = calculate_position_size(
        account_equity=25_000.0,
        entry=101.0,
        stop=100.0,
        risk_per_trade_pct=0.333,
        min_quantity=1,
    )
    assert result.approved is True
    assert result.dollar_risk == pytest.approx(83.25)
    assert result.quantity == 83  # floor(83.25 / 1.0)
    assert result.reason == "ok"


def test_calculate_position_size_rejects_when_quantity_below_minimum():
    # Small account + wide stop -> quantity rounds to 0
    result = calculate_position_size(
        account_equity=500.0,
        entry=110.0,
        stop=100.0,   # $10 stop distance
        risk_per_trade_pct=0.333,
        min_quantity=1,
    )
    assert result.approved is False
    assert result.quantity == 0
    assert "below minimum" in result.reason


def test_calculate_position_size_rejects_zero_stop_distance():
    result = calculate_position_size(
        account_equity=25_000.0,
        entry=100.0,
        stop=100.0,   # no stop distance
        risk_per_trade_pct=0.333,
    )
    assert result.approved is False
    assert result.quantity == 0
    assert "stop_distance" in result.reason


def test_calculate_position_size_rejects_negative_stop_distance_input():
    # entry below stop for a "long" style call still uses abs(), so this
    # should size normally rather than error.
    result = calculate_position_size(
        account_equity=25_000.0,
        entry=100.0,
        stop=101.0,
        risk_per_trade_pct=0.333,
    )
    assert result.approved is True
    assert result.dollar_risk == pytest.approx(83.25)


def test_check_spread_accepts_tight_spread():
    is_ok, spread_pct = check_spread(bid=100.00, ask=100.05, max_spread_pct=0.15)
    assert is_ok is True
    assert spread_pct == pytest.approx(0.05 / 100.025 * 100.0)


def test_check_spread_rejects_wide_spread():
    is_ok, spread_pct = check_spread(bid=100.00, ask=101.00, max_spread_pct=0.15)
    assert is_ok is False
    assert spread_pct > 0.15


def test_check_spread_boundary_exactly_at_max():
    bid, ask = 100.00, 100.15
    mid = (bid + ask) / 2
    max_spread_pct = (ask - bid) / mid * 100.0
    is_ok, spread_pct = check_spread(bid=bid, ask=ask, max_spread_pct=max_spread_pct)
    assert is_ok is True  # <= boundary is acceptable
    assert spread_pct == pytest.approx(max_spread_pct)


def test_check_spread_rejects_crossed_quote():
    is_ok, spread_pct = check_spread(bid=101.0, ask=100.0, max_spread_pct=1.0)
    assert is_ok is False
    assert spread_pct == float("inf")
