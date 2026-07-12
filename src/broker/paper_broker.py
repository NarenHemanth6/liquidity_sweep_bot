"""
broker/paper_broker.py

Simulates order execution with NO connection to any real brokerage, no
network calls, and no credentials of any kind. This is the ONLY broker
implementation in this project.

Explicit safety notes
----------------------
- This module never places a real order; it only maintains in-memory
  state and appends plain-text log lines to a local file.
- There is no LiveBroker class anywhere in this codebase. If a live
  adapter is ever added in a future version, it must live in a fully
  separate module, be off by default, and require both an explicit
  settings.yaml flag and an explicit environment variable to activate
  (see src/config_loader.py:is_live_trading_enabled). None of that
  exists yet, and nothing in this module depends on it.
- No IBKR, Trade The Pool, or any other broker/prop-firm integration is
  implemented or imported here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.strategy.liquidity_sweep import TradeSignal


@dataclass
class Position:
    """An open simulated position.

    Attributes:
        symbol: Ticker symbol.
        direction: "long" or "short".
        quantity: Number of shares.
        entry_price: Filled entry price (including simulated slippage).
        stop_price: Stop-loss price.
        target_prices: Take-profit price levels, in R-multiple order.
        entry_time: Timestamp the position was opened.
        reason_entry: Justification string carried from the TradeSignal.
        swept_level: The PMH/PML/PDH/PDL level swept to trigger entry.
        swept_level_type: Which level was swept -- "PMH"/"PML"/"PDH"/"PDL".
        wick_ratio: The rejection candle's wick ratio at signal time.
        volume_multiple: bar volume / avg_volume at signal time.
        qqq_confirmation: QQQ's classified direction at signal time.
    """

    symbol: str
    direction: str
    quantity: int
    entry_price: float
    stop_price: float
    target_prices: list[float]
    entry_time: datetime
    reason_entry: str
    swept_level: float
    swept_level_type: str
    wick_ratio: float
    volume_multiple: float
    qqq_confirmation: str


def _apply_slippage(price: float, direction: str, slippage_bps: float) -> float:
    """Apply simulated slippage to a fill price.

    Slippage always works against the trader: entries fill slightly
    worse (higher for longs, lower for shorts).

    Args:
        price: Intended fill price.
        direction: "long" or "short".
        slippage_bps: Slippage in basis points (1 bps = 0.01%).

    Returns:
        The adjusted fill price.
    """
    if slippage_bps <= 0:
        return price
    adjustment = price * (slippage_bps / 10_000.0)
    return price + adjustment if direction == "long" else price - adjustment


class PaperBroker:
    """Simulated broker: entries, stop-loss, take-profit, and logging.

    No network I/O and no credentials are used anywhere in this class.
    """

    def __init__(
        self,
        starting_equity: float,
        commission_per_share: float = 0.0,
        slippage_bps: float = 0.0,
        order_log_path: str = "logs/orders.log",
    ) -> None:
        """Initialize the paper broker.

        Args:
            starting_equity: Starting simulated account equity, dollars.
            commission_per_share: Simulated commission charged per share
                on entry and exit (each leg).
            slippage_bps: Simulated slippage in basis points applied to
                entry fills.
            order_log_path: File path to append plain-text order/fill
                log lines to. Parent directories are created if needed.
        """
        self._equity = starting_equity
        self.commission_per_share = commission_per_share
        self.slippage_bps = slippage_bps
        self.order_log_path = order_log_path

        log_dir = Path(order_log_path).parent
        if str(log_dir) not in ("", "."):
            log_dir.mkdir(parents=True, exist_ok=True)

    @property
    def equity(self) -> float:
        """Return current simulated account equity.

        Returns:
            The account equity in dollars, updated by every closed
            trade's P&L (commissions included).
        """
        return self._equity

    def _log(self, line: str) -> None:
        """Append a single line to the order log file.

        Args:
            line: The text line to append (a newline is added).
        """
        with open(self.order_log_path, "a", encoding="utf-8") as f:
            f.write(line.rstrip("\n") + "\n")

    def submit_bracket_order(self, signal: TradeSignal, quantity: int) -> Position:
        """Simulate submitting a bracket order (entry + stop + targets).

        The entry is assumed to fill immediately at the signal's entry
        price, adjusted for simulated slippage. In this simplified
        simulator, only the first (nearest, i.e. lowest R) target is
        tracked as the active take-profit level for process_bar(); all
        configured targets are retained on the Position for reference
        and journaling.

        Args:
            signal: The TradeSignal describing entry/stop/targets.
            quantity: Number of shares to trade, from position sizing.

        Returns:
            The newly opened Position.

        Raises:
            ValueError: If quantity is not positive.
        """
        if quantity <= 0:
            raise ValueError("quantity must be positive to submit an order")

        fill_price = _apply_slippage(signal.entry, signal.direction, self.slippage_bps)

        position = Position(
            symbol=signal.symbol,
            direction=signal.direction,
            quantity=quantity,
            entry_price=fill_price,
            stop_price=signal.stop,
            target_prices=list(signal.targets),
            entry_time=signal.timestamp,
            reason_entry=signal.reason_entry,
            swept_level=signal.swept_level,
            swept_level_type=signal.swept_level_type,
            wick_ratio=signal.wick_ratio,
            volume_multiple=signal.volume_multiple,
            qqq_confirmation=signal.qqq_confirmation,
        )

        self._log(
            f"{signal.timestamp} ENTRY {signal.symbol} {signal.direction} "
            f"qty={quantity} fill={fill_price:.4f} stop={signal.stop:.4f} "
            f"targets={signal.targets} reason='{signal.reason_entry}'"
        )
        return position

    def _close_position(
        self,
        position: Position,
        exit_price: float,
        exit_time: datetime,
        exit_reason: str,
    ) -> dict[str, Any]:
        """Finalize a position close: compute P&L, update equity, log it.

        Args:
            position: The Position being closed.
            exit_price: Fill price for the closing trade.
            exit_time: Timestamp of the close.
            exit_reason: "stop" | "target_2.5R" | "target_3R" |
                "force_flat" | "eod".

        Returns:
            A trade record dict suitable for TradeJournal.record_trade,
            containing: timestamp, entry_time, symbol, direction,
            swept_level, swept_level_type, entry, stop, target,
            risk_amount, quantity, exit, pnl, r_multiple, wick_ratio,
            volume_multiple, qqq_confirmation, reason_entry,
            reason_exit.
        """
        if position.direction == "long":
            gross_pnl = (exit_price - position.entry_price) * position.quantity
        else:
            gross_pnl = (position.entry_price - exit_price) * position.quantity

        commission = self.commission_per_share * position.quantity * 2  # entry + exit
        pnl = gross_pnl - commission
        self._equity += pnl

        risk_amount = abs(position.entry_price - position.stop_price) * position.quantity
        r_multiple = pnl / risk_amount if risk_amount > 0 else 0.0

        self._log(
            f"{exit_time} EXIT {position.symbol} {position.direction} "
            f"qty={position.quantity} fill={exit_price:.4f} "
            f"reason={exit_reason} pnl={pnl:.2f}"
        )

        target_label = ", ".join(f"{t:.2f}" for t in position.target_prices)

        return {
            "timestamp": exit_time,
            "entry_time": position.entry_time,
            "symbol": position.symbol,
            "direction": position.direction,
            "swept_level": position.swept_level,
            "swept_level_type": position.swept_level_type,
            "entry": position.entry_price,
            "stop": position.stop_price,
            "target": target_label,
            "risk_amount": risk_amount,
            "quantity": position.quantity,
            "exit": exit_price,
            "pnl": pnl,
            "r_multiple": r_multiple,
            "wick_ratio": position.wick_ratio,
            "volume_multiple": position.volume_multiple,
            "qqq_confirmation": position.qqq_confirmation,
            "reason_entry": position.reason_entry,
            "reason_exit": exit_reason,
        }

    def process_bar(self, position: Position, bar: dict[str, Any]) -> dict[str, Any] | None:
        """Check a new bar against an open position's stop and targets.

        Stop-loss is checked before take-profit within the same bar
        (a conservative assumption when both could theoretically be hit
        intrabar). Only the nearest configured target
        (position.target_prices[0]) is used to trigger a close; this
        keeps the v1 simulator simple (single take-profit level).

        Args:
            position: The currently open Position.
            bar: The new OHLCV bar (dict with "timestamp", "high",
                "low", and other OHLCV keys).

        Returns:
            A trade record dict (see _close_position) if the position
            closed on this bar, otherwise None.
        """
        if position.direction == "long":
            if bar["low"] <= position.stop_price:
                return self._close_position(
                    position, position.stop_price, bar["timestamp"], "stop"
                )
            if position.target_prices and bar["high"] >= position.target_prices[0]:
                return self._close_position(
                    position,
                    position.target_prices[0],
                    bar["timestamp"],
                    "target_2.5R",
                )
        else:
            if bar["high"] >= position.stop_price:
                return self._close_position(
                    position, position.stop_price, bar["timestamp"], "stop"
                )
            if position.target_prices and bar["low"] <= position.target_prices[0]:
                return self._close_position(
                    position,
                    position.target_prices[0],
                    bar["timestamp"],
                    "target_2.5R",
                )
        return None

    def force_close(self, position: Position, bar: dict[str, Any]) -> dict[str, Any]:
        """Force-close a position at the given bar's close price.

        Used for the 1:00 PM ET forced end-of-session flatten.

        Args:
            position: The currently open Position.
            bar: The bar whose close price will be used as the exit
                fill (dict with "timestamp" and "close" keys).

        Returns:
            A trade record dict (see _close_position).
        """
        return self._close_position(
            position, bar["close"], bar["timestamp"], "force_flat"
        )
