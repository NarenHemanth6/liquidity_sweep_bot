"""
risk/position_sizing.py

Converts a TradeSignal + account state into a concrete order quantity,
or rejects the trade with a clear reason. Pure calculation module: no
I/O, no broker calls.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class SizingResult:
    """Result of a position-sizing calculation.

    Attributes:
        approved: Whether the trade may proceed.
        quantity: Computed share quantity (0 if not approved).
        dollar_risk: Dollar amount risked at the computed quantity.
        reason: "ok" if approved, otherwise a human-readable rejection
            reason.
    """

    approved: bool
    quantity: int
    dollar_risk: float
    reason: str


def calculate_position_size(
    account_equity: float,
    entry: float,
    stop: float,
    risk_per_trade_pct: float,
    min_quantity: int = 1,
) -> SizingResult:
    """Compute share quantity for a trade sized to a fixed % account risk.

    dollar_risk   = account_equity * (risk_per_trade_pct / 100)
    stop_distance = abs(entry - stop)
    quantity      = floor(dollar_risk / stop_distance)

    Args:
        account_equity: Current account equity in dollars.
        entry: Proposed entry price.
        stop: Proposed stop-loss price.
        risk_per_trade_pct: Percent of account equity to risk on this
            trade, e.g. 0.333 for 0.333%.
        min_quantity: Minimum acceptable share quantity. Trades sizing
            below this are rejected. Defaults to 1.

    Returns:
        A SizingResult. `approved` is False if stop_distance <= 0 or
        the computed quantity is below `min_quantity`; in either case
        `quantity` is 0 and `reason` explains why.
    """
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return SizingResult(
            approved=False,
            quantity=0,
            dollar_risk=0.0,
            reason="stop_distance must be greater than zero",
        )

    dollar_risk = account_equity * (risk_per_trade_pct / 100.0)
    quantity = math.floor(dollar_risk / stop_distance)

    if quantity < min_quantity:
        return SizingResult(
            approved=False,
            quantity=0,
            dollar_risk=dollar_risk,
            reason=(
                f"computed quantity {quantity} is below minimum "
                f"{min_quantity} (stop too wide for account size)"
            ),
        )

    return SizingResult(
        approved=True,
        quantity=quantity,
        dollar_risk=dollar_risk,
        reason="ok",
    )


def check_spread(bid: float, ask: float, max_spread_pct: float) -> tuple[bool, float]:
    """Check whether the bid/ask spread is acceptable to trade.

    spread_pct = (ask - bid) / mid_price * 100, where
    mid_price = (bid + ask) / 2

    Args:
        bid: Current bid price.
        ask: Current ask price.
        max_spread_pct: Maximum acceptable spread as a percent of mid
            price.

    Returns:
        A tuple (is_acceptable, spread_pct). is_acceptable is False if
        ask <= bid (invalid/crossed quote) or mid_price <= 0, in
        addition to the normal spread_pct > max_spread_pct case.
    """
    if ask <= bid:
        return False, float("inf")

    mid_price = (bid + ask) / 2.0
    if mid_price <= 0:
        return False, float("inf")

    spread_pct = (ask - bid) / mid_price * 100.0
    return spread_pct <= max_spread_pct, spread_pct
