"""
risk/risk_controls.py

Daily kill-switch and trade-gating logic. Consulted before every new
trade is allowed, and drives the forced end-of-session flatten. Pure
in-memory state: no I/O, no broker calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


@dataclass
class DailyRiskState:
    """Mutable per-day risk-tracking state.

    Attributes:
        trades_taken: Number of trades filled today.
        consecutive_losses: Current streak of consecutive losing trades.
        realized_pnl: Cumulative realized P&L for today, in dollars.
        starting_equity: Account equity at the start of today.
        halted: Whether trading has been halted for the rest of today.
        halt_reason: Human-readable reason trading was halted, if any.
    """

    trades_taken: int = 0
    consecutive_losses: int = 0
    realized_pnl: float = 0.0
    starting_equity: float = 0.0
    halted: bool = False
    halt_reason: str = ""


class RiskManager:
    """Enforces daily kill-switch rules and session time cutoffs.

    Config keys expected in `cfg`:
        max_trades_per_day (int)
        max_daily_loss_pct (float)      # e.g. 1.0 for 1%
        max_consecutive_losses (int)
        no_new_trades_after (str)       # "HH:MM", 24h, in `timezone`
        force_flat_time (str)           # "HH:MM", 24h, in `timezone`
        timezone (str, optional)        # defaults to "America/New_York"
    """

    def __init__(self, cfg: Mapping[str, Any], starting_equity: float) -> None:
        """Initialize the risk manager for a new trading day.

        Args:
            cfg: Risk/session configuration, see class docstring for
                expected keys.
            starting_equity: Account equity at the start of the day.
        """
        self.cfg = cfg
        self.timezone = cfg.get("timezone", "America/New_York")
        self.state = DailyRiskState(starting_equity=starting_equity)

    def _time_str(self, now: datetime) -> str:
        """Return `now` formatted as "HH:MM" in the configured timezone.

        Args:
            now: A tz-aware datetime.

        Returns:
            "HH:MM" string in `self.timezone`.

        Raises:
            ValueError: If `now` is not tz-aware.
        """
        if now.tzinfo is None:
            raise ValueError("`now` must be a tz-aware datetime")
        try:
            from zoneinfo import ZoneInfo

            localized = now.astimezone(ZoneInfo(self.timezone))
        except ImportError:  # pragma: no cover - zoneinfo is stdlib 3.9+
            localized = now
        return localized.strftime("%H:%M")

    def can_open_new_trade(self, now: datetime) -> tuple[bool, str]:
        """Check whether a new trade may be opened right now.

        Checks, in order: an existing halt, max trades per day, max
        daily loss, max consecutive losses, and the no-new-trades time
        cutoff.

        Args:
            now: Current tz-aware datetime.

        Returns:
            (allowed, reason). `reason` is "ok" if allowed, otherwise a
            human-readable explanation of the block.
        """
        if self.state.halted:
            return False, f"trading halted: {self.state.halt_reason}"

        if self.state.trades_taken >= self.cfg["max_trades_per_day"]:
            return False, (
                f"max trades per day reached "
                f"({self.cfg['max_trades_per_day']})"
            )

        max_loss_dollars = self.state.starting_equity * (
            self.cfg["max_daily_loss_pct"] / 100.0
        )
        if self.state.realized_pnl <= -max_loss_dollars:
            return False, (
                f"max daily loss reached "
                f"({self.cfg['max_daily_loss_pct']}% of starting equity)"
            )

        if self.state.consecutive_losses >= self.cfg["max_consecutive_losses"]:
            return False, (
                f"max consecutive losses reached "
                f"({self.cfg['max_consecutive_losses']})"
            )

        if self._time_str(now) >= self.cfg["no_new_trades_after"]:
            return False, (
                f"no new trades allowed after "
                f"{self.cfg['no_new_trades_after']}"
            )

        return True, "ok"

    def register_trade_result(self, pnl: float) -> None:
        """Record the outcome of a completed trade.

        Updates trades_taken, consecutive_losses, and realized_pnl,
        then evaluates whether the daily loss limit has now been
        breached (setting `halted`/`halt_reason` if so).

        Args:
            pnl: Realized profit (positive) or loss (negative) in
                dollars for the completed trade.
        """
        self.state.trades_taken += 1
        self.state.realized_pnl += pnl

        if pnl < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0

        max_loss_dollars = self.state.starting_equity * (
            self.cfg["max_daily_loss_pct"] / 100.0
        )
        if self.state.realized_pnl <= -max_loss_dollars:
            self.state.halted = True
            self.state.halt_reason = (
                f"daily loss limit breached "
                f"({self.cfg['max_daily_loss_pct']}% of starting equity)"
            )
        elif self.state.consecutive_losses >= self.cfg["max_consecutive_losses"]:
            self.state.halted = True
            self.state.halt_reason = (
                f"{self.state.consecutive_losses} consecutive losses reached"
            )

    def should_force_flat(self, now: datetime) -> bool:
        """Determine whether open positions must be force-closed now.

        Args:
            now: Current tz-aware datetime.

        Returns:
            True if `now`'s time-of-day (in the configured timezone) is
            at or after `cfg["force_flat_time"]`.
        """
        return self._time_str(now) >= self.cfg["force_flat_time"]

    def reset_for_new_day(self, starting_equity: float) -> None:
        """Reset all daily counters for a new trading day.

        Args:
            starting_equity: Account equity at the start of the new day.
        """
        self.state = DailyRiskState(starting_equity=starting_equity)
