"""
journal/trade_journal.py

Append-only record of every simulated trade, written to CSV so trades
are auditable after the fact. Written to by the caller (typically
main.py) whenever PaperBroker closes a position.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pandas as pd

REQUIRED_COLUMNS = (
    "timestamp",
    "entry_time",
    "symbol",
    "direction",
    "swept_level",
    "swept_level_type",
    "entry",
    "stop",
    "target",
    "risk_amount",
    "quantity",
    "exit",
    "pnl",
    "r_multiple",
    "wick_ratio",
    "volume_multiple",
    "qqq_confirmation",
    "reason_entry",
    "reason_exit",
)


class TradeJournal:
    """CSV-backed trade journal. Append-only within a run; optionally
    starts each run from a clean file via `overwrite`."""

    def __init__(self, path: str = "logs/trade_journal.csv", overwrite: bool = False) -> None:
        """Initialize the journal, ensuring the parent directory exists.

        Args:
            path: File path for the CSV journal.
            overwrite: If True, delete any existing file at `path` right
                now, so the first record_trade() call starts a fresh
                file (previous runs' rows are not carried over). If
                False (this class's default), an existing file is left
                alone and new trades are appended to it.

                This class's own default is non-destructive so that
                constructing a TradeJournal purely to call read_all()
                (e.g. to print a summary after a run) never wipes data
                a previous TradeJournal instance just wrote. Callers
                that want "fresh journal every run" -- e.g. every
                backtest -- pass overwrite=True explicitly; see
                src.backtesting.engine.run_backtest's own
                overwrite_journal parameter (default True), which is
                the default actually experienced by every backtest CLI
                script.
        """
        self.path = path
        parent = Path(path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        if overwrite:
            file_path = Path(path)
            if file_path.exists():
                file_path.unlink()

    def record_trade(self, trade_record: dict[str, Any]) -> None:
        """Append one completed trade to the journal.

        Creates the file with a header row if it doesn't exist yet.

        Args:
            trade_record: Dict containing all keys in REQUIRED_COLUMNS.

        Raises:
            ValueError: If `trade_record` is missing any required key.
        """
        missing = [c for c in REQUIRED_COLUMNS if c not in trade_record]
        if missing:
            raise ValueError(f"trade_record is missing required keys: {missing}")

        file_path = Path(self.path)
        file_exists = file_path.exists() and file_path.stat().st_size > 0

        with open(self.path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(REQUIRED_COLUMNS))
            if not file_exists:
                writer.writeheader()
            writer.writerow({col: trade_record[col] for col in REQUIRED_COLUMNS})

    def read_all(self) -> pd.DataFrame:
        """Load the full journal as a DataFrame.

        Returns:
            A DataFrame with REQUIRED_COLUMNS. Empty (but correctly
            columned) DataFrame if the journal file doesn't exist yet.
        """
        file_path = Path(self.path)
        if not file_path.exists():
            return pd.DataFrame(columns=list(REQUIRED_COLUMNS))
        return pd.read_csv(self.path)

    def daily_summary(self, date: Any) -> dict[str, Any]:
        """Summarize trades for a given date.

        Args:
            date: A date-like value (str "YYYY-MM-DD" or date/datetime)
                matched against the date portion of each trade's
                timestamp.

        Returns:
            A dict with keys: trades_taken, wins, losses, total_pnl,
            win_rate (0.0-1.0, or 0.0 if trades_taken is 0).
        """
        df = self.read_all()
        if df.empty:
            return {
                "trades_taken": 0,
                "wins": 0,
                "losses": 0,
                "total_pnl": 0.0,
                "win_rate": 0.0,
            }

        target_date = pd.to_datetime(date).date()
        df["_ts"] = pd.to_datetime(df["timestamp"])
        day_df = df[df["_ts"].dt.date == target_date]

        trades_taken = len(day_df)
        wins = int((day_df["pnl"] > 0).sum())
        losses = int((day_df["pnl"] <= 0).sum())
        total_pnl = float(day_df["pnl"].sum())
        win_rate = wins / trades_taken if trades_taken > 0 else 0.0

        return {
            "trades_taken": trades_taken,
            "wins": wins,
            "losses": losses,
            "total_pnl": total_pnl,
            "win_rate": win_rate,
        }
