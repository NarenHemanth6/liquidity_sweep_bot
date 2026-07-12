"""
scripts/analyze_backtest_results.py

Reads a per-trade journal CSV (default: logs/real_csv_backtest_journal.csv,
as written by scripts/run_real_csv_backtest.py / scripts/run_backtest.py)
and prints a diagnostic report explaining WHY the strategy won or lost --
broken down by date, symbol, direction, level swept, QQQ confirmation,
wick ratio, volume spike, R-multiple, and exit reason.

This script only ever reads a local CSV file with pandas. It does not
change any entry/exit strategy logic, does not optimize any parameter,
does not add broker execution, and never connects to a network or
broker of any kind -- paper/simulation diagnostics only.

Usage:
    python -m scripts.analyze_backtest_results
    python -m scripts.analyze_backtest_results --journal-path logs/backtest_trade_journal.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.journal.trade_journal import TradeJournal  # noqa: E402

DEFAULT_JOURNAL_PATH = "logs/real_csv_backtest_journal.csv"


def load_journal(path: str) -> pd.DataFrame:
    """Load a trade journal CSV, parsing timestamp columns.

    Args:
        path: Path to the journal CSV (TradeJournal.REQUIRED_COLUMNS schema).

    Returns:
        A DataFrame with "timestamp" and "entry_time" parsed as
        datetimes. Empty (but correctly columned) if the file doesn't
        exist or has no rows.
    """
    df = TradeJournal(path).read_all()
    if df.empty:
        return df
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    return df


def compute_r_multiple(pnl: float, risk_amount: float) -> float:
    """Realized R-multiple = pnl / initial dollar risk.

    Recomputed independently from pnl/risk_amount here (rather than
    trusting the journal's own r_multiple column) so this diagnostic
    is self-checking.

    Args:
        pnl: Realized profit/loss in dollars for one trade.
        risk_amount: Initial dollar risk for that trade (>= 0).

    Returns:
        pnl / risk_amount, or 0.0 if risk_amount is zero or negative
        (a trade with no defined risk has no meaningful R-multiple).
    """
    if risk_amount <= 0:
        return 0.0
    return pnl / risk_amount


def with_r_multiple(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df with an independently-recomputed 'r_multiple' column."""
    df = df.copy()
    df["r_multiple"] = [
        compute_r_multiple(pnl, risk_amount) for pnl, risk_amount in zip(df["pnl"], df["risk_amount"])
    ]
    return df


def _is_win(df: pd.DataFrame) -> pd.Series:
    return df["pnl"] > 0


def trades_by_date(df: pd.DataFrame) -> pd.DataFrame:
    """Trade count and net P&L per calendar date (grouped by entry_time's date)."""
    if df.empty:
        return pd.DataFrame(columns=["date", "trades", "pnl"])
    grouped = df.groupby(df["entry_time"].dt.date).agg(trades=("pnl", "size"), pnl=("pnl", "sum"))
    return grouped.reset_index().rename(columns={"entry_time": "date"}).sort_values("date")


def trades_by_symbol(df: pd.DataFrame) -> pd.DataFrame:
    """Trade count and net P&L per symbol."""
    if df.empty:
        return pd.DataFrame(columns=["symbol", "trades", "pnl"])
    grouped = df.groupby("symbol").agg(trades=("pnl", "size"), pnl=("pnl", "sum"))
    return grouped.reset_index().sort_values("symbol")


def trades_by_direction(df: pd.DataFrame) -> pd.DataFrame:
    """Trade count and net P&L per direction (long/short)."""
    if df.empty:
        return pd.DataFrame(columns=["direction", "trades", "pnl"])
    grouped = df.groupby("direction").agg(trades=("pnl", "size"), pnl=("pnl", "sum"))
    return grouped.reset_index().sort_values("direction")


def _win_loss_breakdown(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """Shared win/loss-by-<group_col> aggregation (symbol or direction)."""
    columns = [group_col, "trades", "wins", "losses", "win_rate", "pnl"]
    if df.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for key, group in df.groupby(group_col):
        wins = int(_is_win(group).sum())
        losses = len(group) - wins
        rows.append(
            {
                group_col: key,
                "trades": len(group),
                "wins": wins,
                "losses": losses,
                "win_rate": wins / len(group) if len(group) else 0.0,
                "pnl": float(group["pnl"].sum()),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(group_col)


def win_loss_by_symbol(df: pd.DataFrame) -> pd.DataFrame:
    """Wins/losses/win-rate/P&L per symbol."""
    return _win_loss_breakdown(df, "symbol")


def win_loss_by_direction(df: pd.DataFrame) -> pd.DataFrame:
    """Wins/losses/win-rate/P&L per direction (long/short)."""
    return _win_loss_breakdown(df, "direction")


def average_win(df: pd.DataFrame) -> float:
    """Average P&L of winning trades (pnl > 0), or 0.0 if there are none."""
    if df.empty:
        return 0.0
    wins = df.loc[_is_win(df), "pnl"]
    return float(wins.mean()) if not wins.empty else 0.0


def average_loss(df: pd.DataFrame) -> float:
    """Average P&L of losing trades (pnl <= 0, so this is <= 0), or 0.0 if there are none."""
    if df.empty:
        return 0.0
    losses = df.loc[~_is_win(df), "pnl"]
    return float(losses.mean()) if not losses.empty else 0.0


def largest_win(df: pd.DataFrame) -> dict[str, Any] | None:
    """The single winning trade with the highest P&L, or None if there are no wins."""
    if df.empty:
        return None
    wins = df.loc[_is_win(df)]
    if wins.empty:
        return None
    return wins.loc[wins["pnl"].idxmax()].to_dict()


def largest_loss(df: pd.DataFrame) -> dict[str, Any] | None:
    """The single losing trade with the lowest (most negative) P&L, or None if there are no losses."""
    if df.empty:
        return None
    losses = df.loc[~_is_win(df)]
    if losses.empty:
        return None
    return losses.loc[losses["pnl"].idxmin()].to_dict()


def max_consecutive_losses(df: pd.DataFrame) -> int:
    """Longest streak of consecutive losing trades (pnl <= 0), in entry-time order."""
    if df.empty:
        return 0
    ordered = df.sort_values("entry_time")
    longest = current = 0
    for is_loss in ~_is_win(ordered):
        if is_loss:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def time_of_day_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Trade count, win rate, and net P&L bucketed by entry hour (HH:00)."""
    columns = ["hour", "trades", "wins", "win_rate", "pnl"]
    if df.empty:
        return pd.DataFrame(columns=columns)
    hour = df["entry_time"].dt.strftime("%H:00")
    rows = []
    for key, group in df.groupby(hour):
        wins = int(_is_win(group).sum())
        rows.append(
            {
                "hour": key,
                "trades": len(group),
                "wins": wins,
                "win_rate": wins / len(group) if len(group) else 0.0,
                "pnl": float(group["pnl"].sum()),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values("hour")


def level_swept_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Trade count, win rate, and net P&L bucketed by swept_level_type (PMH/PML/PDH/PDL)."""
    columns = ["swept_level_type", "trades", "wins", "win_rate", "pnl"]
    if df.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for key, group in df.groupby("swept_level_type"):
        wins = int(_is_win(group).sum())
        rows.append(
            {
                "swept_level_type": key,
                "trades": len(group),
                "wins": wins,
                "win_rate": wins / len(group) if len(group) else 0.0,
                "pnl": float(group["pnl"].sum()),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values("swept_level_type")


def qqq_confirmation_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Trade count, win rate, and net P&L bucketed by qqq_confirmation (bullish/bearish/neutral)."""
    columns = ["qqq_confirmation", "trades", "wins", "win_rate", "pnl"]
    if df.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for key, group in df.groupby("qqq_confirmation"):
        wins = int(_is_win(group).sum())
        rows.append(
            {
                "qqq_confirmation": key,
                "trades": len(group),
                "wins": wins,
                "win_rate": wins / len(group) if len(group) else 0.0,
                "pnl": float(group["pnl"].sum()),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values("qqq_confirmation")


def wick_ratio_stats(df: pd.DataFrame) -> dict[str, float]:
    """Average wick_ratio at entry, overall and split by win/loss."""
    if df.empty:
        return {"overall": 0.0, "wins": 0.0, "losses": 0.0}
    wins = df.loc[_is_win(df), "wick_ratio"]
    losses = df.loc[~_is_win(df), "wick_ratio"]
    return {
        "overall": float(df["wick_ratio"].mean()),
        "wins": float(wins.mean()) if not wins.empty else 0.0,
        "losses": float(losses.mean()) if not losses.empty else 0.0,
    }


def volume_multiple_stats(df: pd.DataFrame) -> dict[str, float]:
    """Average volume_multiple at entry, overall and split by win/loss."""
    if df.empty:
        return {"overall": 0.0, "wins": 0.0, "losses": 0.0}
    wins = df.loc[_is_win(df), "volume_multiple"]
    losses = df.loc[~_is_win(df), "volume_multiple"]
    return {
        "overall": float(df["volume_multiple"].mean()),
        "wins": float(wins.mean()) if not wins.empty else 0.0,
        "losses": float(losses.mean()) if not losses.empty else 0.0,
    }


def average_r_multiple(df: pd.DataFrame) -> float:
    """Average recomputed R-multiple across all trades."""
    if df.empty:
        return 0.0
    return float(with_r_multiple(df)["r_multiple"].mean())


def exit_reason_breakdown(df: pd.DataFrame) -> dict[str, int]:
    """Count of trades per reason_exit value (e.g. 'stop', 'target_2.5R', 'target_3R', 'force_flat')."""
    if df.empty:
        return {}
    return df["reason_exit"].value_counts().to_dict()


def stop_out_count(df: pd.DataFrame) -> int:
    """Count of trades closed via a stop-loss (reason_exit == 'stop')."""
    return exit_reason_breakdown(df).get("stop", 0)


def _print_group_table(title: str, table: pd.DataFrame) -> None:
    print(f"\n{title}")
    if table.empty:
        print("  (no trades)")
        return
    for _, row in table.iterrows():
        parts = []
        for col in table.columns:
            value = row[col]
            if col == "win_rate":
                parts.append(f"win_rate={value * 100:.1f}%")
            elif col == "pnl":
                parts.append(f"pnl=${value:.2f}")
            elif isinstance(value, float):
                parts.append(f"{col}={value:.2f}")
            else:
                parts.append(f"{col}={value}")
        print("  " + "  ".join(parts))


def print_report(df: pd.DataFrame) -> None:
    """Print the full diagnostic report for a loaded journal DataFrame."""
    print("=" * 70)
    print("BACKTEST DIAGNOSTIC REPORT (paper/simulation only)")
    print("=" * 70)

    if df.empty:
        print("\nNo trades found in this journal.")
        print("=" * 70)
        return

    print(f"\nTotal trades: {len(df)}")

    _print_group_table("Trades by date:", trades_by_date(df))
    _print_group_table("Trades by symbol:", trades_by_symbol(df))
    _print_group_table("Trades by direction:", trades_by_direction(df))
    _print_group_table("Win/loss by symbol:", win_loss_by_symbol(df))
    _print_group_table("Win/loss by direction:", win_loss_by_direction(df))

    print("\nWin/loss summary:")
    print(f"  Average win:   ${average_win(df):.2f}")
    print(f"  Average loss:  ${average_loss(df):.2f}")
    win = largest_win(df)
    loss = largest_loss(df)
    if win is not None:
        print(f"  Largest win:   {win['symbol']} {win['direction']} pnl=${win['pnl']:.2f} ({win['entry_time']})")
    else:
        print("  Largest win:   (no wins)")
    if loss is not None:
        print(f"  Largest loss:  {loss['symbol']} {loss['direction']} pnl=${loss['pnl']:.2f} ({loss['entry_time']})")
    else:
        print("  Largest loss:  (no losses)")
    print(f"  Max consecutive losses: {max_consecutive_losses(df)}")

    _print_group_table("Time of day performance (by entry hour):", time_of_day_performance(df))
    _print_group_table("Level swept performance (PMH/PML/PDH/PDL):", level_swept_performance(df))
    _print_group_table("QQQ confirmation value at entry:", qqq_confirmation_performance(df))

    wick_stats = wick_ratio_stats(df)
    print("\nWick ratio at entry:")
    print(f"  Overall avg: {wick_stats['overall']:.2f}")
    print(f"  Wins avg:    {wick_stats['wins']:.2f}")
    print(f"  Losses avg:  {wick_stats['losses']:.2f}")

    vol_stats = volume_multiple_stats(df)
    print("\nVolume spike at entry (bar volume / avg volume):")
    print(f"  Overall avg: {vol_stats['overall']:.2f}x")
    print(f"  Wins avg:    {vol_stats['wins']:.2f}x")
    print(f"  Losses avg:  {vol_stats['losses']:.2f}x")

    print(f"\nAverage R-multiple: {average_r_multiple(df):.2f}R")
    print("R-multiple per trade:")
    r_df = with_r_multiple(df).sort_values("entry_time")
    for _, row in r_df.iterrows():
        print(
            f"  {row['entry_time']}  {row['symbol']:<6} {row['direction']:<5} "
            f"r_multiple={row['r_multiple']:+.2f}R  pnl=${row['pnl']:.2f}  exit_reason={row['reason_exit']}"
        )

    reasons = exit_reason_breakdown(df)
    print("\nExit reason breakdown:")
    print(f"  Stop-outs:          {reasons.get('stop', 0)}")
    print(f"  Reached 2.5R target: {reasons.get('target_2.5R', 0)}")
    print(f"  Reached 3R target:   {reasons.get('target_3R', 0)}")
    print(f"  Force-flat (EOD):   {reasons.get('force_flat', 0)}")
    other = {k: v for k, v in reasons.items() if k not in ("stop", "target_2.5R", "target_3R", "force_flat")}
    if other:
        print(f"  Other:              {other}")

    print("\n" + "=" * 70)


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the diagnostic run."""
    parser = argparse.ArgumentParser(description="Print a diagnostic report for a backtest trade journal.")
    parser.add_argument(
        "--journal-path",
        default=DEFAULT_JOURNAL_PATH,
        help=f"Path to the journal CSV to analyze (default: {DEFAULT_JOURNAL_PATH})",
    )
    return parser.parse_args()


def main() -> None:
    """Load the journal and print the full diagnostic report."""
    args = _parse_args()
    df = load_journal(args.journal_path)
    print_report(df)


if __name__ == "__main__":
    main()
