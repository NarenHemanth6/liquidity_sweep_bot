"""Tests for src/backtesting/metrics.py -- pure calculation, no I/O."""

from __future__ import annotations

import pytest

from src.backtesting.metrics import compute_metrics


def _trade(pnl):
    return {"pnl": pnl}


def test_no_trades_returns_zeroed_metrics():
    metrics = compute_metrics([], starting_equity=25_000.0)

    assert metrics["total_trades"] == 0
    assert metrics["wins"] == 0
    assert metrics["losses"] == 0
    assert metrics["win_rate"] == 0.0
    assert metrics["gross_profit"] == 0
    assert metrics["gross_loss"] == 0
    assert metrics["net_pnl"] == 0
    assert metrics["average_win"] == 0.0
    assert metrics["average_loss"] == 0.0
    assert metrics["profit_factor"] == 0.0
    assert metrics["max_drawdown"] == 0.0
    assert metrics["ending_equity"] == 25_000.0


def test_wins_and_losses_are_classified_and_counted():
    trades = [_trade(100.0), _trade(-40.0), _trade(50.0), _trade(-10.0), _trade(0.0)]

    metrics = compute_metrics(trades, starting_equity=10_000.0)

    assert metrics["total_trades"] == 5
    assert metrics["wins"] == 2  # 100.0, 50.0
    assert metrics["losses"] == 3  # -40.0, -10.0, 0.0 (a zero-pnl trade counts as a loss, not a win)
    assert metrics["win_rate"] == pytest.approx(2 / 5)


def test_gross_profit_gross_loss_and_net_pnl():
    trades = [_trade(100.0), _trade(50.0), _trade(-40.0), _trade(-10.0)]

    metrics = compute_metrics(trades, starting_equity=10_000.0)

    assert metrics["gross_profit"] == pytest.approx(150.0)
    assert metrics["gross_loss"] == pytest.approx(-50.0)
    assert metrics["net_pnl"] == pytest.approx(100.0)


def test_average_win_and_average_loss():
    trades = [_trade(100.0), _trade(50.0), _trade(-40.0), _trade(-10.0)]

    metrics = compute_metrics(trades, starting_equity=10_000.0)

    assert metrics["average_win"] == pytest.approx(75.0)  # (100+50)/2
    assert metrics["average_loss"] == pytest.approx(-25.0)  # (-40-10)/2


def test_profit_factor_normal_case():
    trades = [_trade(200.0), _trade(-100.0)]

    metrics = compute_metrics(trades, starting_equity=10_000.0)

    assert metrics["profit_factor"] == pytest.approx(2.0)


def test_profit_factor_is_infinite_with_only_wins():
    trades = [_trade(100.0), _trade(50.0)]

    metrics = compute_metrics(trades, starting_equity=10_000.0)

    assert metrics["profit_factor"] == float("inf")


def test_profit_factor_is_zero_with_no_wins_and_no_losses():
    trades = [_trade(0.0)]

    metrics = compute_metrics(trades, starting_equity=10_000.0)

    assert metrics["profit_factor"] == 0.0


def test_max_drawdown_tracks_the_worst_peak_to_trough_decline():
    # equity path: 10000 -> 10100 (peak) -> 9900 (dd=200) -> 10050 -> 9800 (dd=300, new max)
    trades = [_trade(100.0), _trade(-200.0), _trade(150.0), _trade(-250.0)]

    metrics = compute_metrics(trades, starting_equity=10_000.0)

    assert metrics["max_drawdown"] == pytest.approx(300.0)


def test_max_drawdown_is_zero_when_equity_never_declines():
    trades = [_trade(50.0), _trade(50.0), _trade(50.0)]

    metrics = compute_metrics(trades, starting_equity=10_000.0)

    assert metrics["max_drawdown"] == 0.0


def test_ending_equity_equals_starting_equity_plus_net_pnl():
    trades = [_trade(100.0), _trade(-40.0), _trade(25.0)]

    metrics = compute_metrics(trades, starting_equity=5_000.0)

    assert metrics["ending_equity"] == pytest.approx(5_000.0 + metrics["net_pnl"])
