"""
backtesting/metrics.py

Turns a list of closed-trade records (as produced by PaperBroker /
TradeJournal) into aggregate backtest performance metrics. Pure
calculation module: no I/O, no broker calls.
"""

from __future__ import annotations

from typing import Any


def compute_metrics(trades: list[dict[str, Any]], starting_equity: float) -> dict[str, Any]:
    """Compute aggregate performance metrics from a list of closed trades.

    Args:
        trades: List of trade record dicts, in chronological order,
            each containing at least a "pnl" key (float; positive for
            wins, non-positive for losses).
        starting_equity: Account equity before the first trade.

    Returns:
        A dict with keys: total_trades, wins, losses, win_rate,
        gross_profit, gross_loss (<= 0), net_pnl, average_win,
        average_loss (<= 0), profit_factor, max_drawdown,
        ending_equity.

        profit_factor is float("inf") if there are wins and no losses,
        or 0.0 if there are neither wins nor losses.
    """
    total_trades = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]

    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = sum(t["pnl"] for t in losses)
    net_pnl = gross_profit + gross_loss

    win_rate = len(wins) / total_trades if total_trades else 0.0
    average_win = gross_profit / len(wins) if wins else 0.0
    average_loss = gross_loss / len(losses) if losses else 0.0

    if gross_loss == 0:
        profit_factor = float("inf") if gross_profit > 0 else 0.0
    else:
        profit_factor = gross_profit / abs(gross_loss)

    equity = starting_equity
    peak = starting_equity
    max_drawdown = 0.0
    for trade in trades:
        equity += trade["pnl"]
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    return {
        "total_trades": total_trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "net_pnl": net_pnl,
        "average_win": average_win,
        "average_loss": average_loss,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "ending_equity": equity,
    }
