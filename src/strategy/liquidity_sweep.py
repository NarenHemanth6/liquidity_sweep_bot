"""
strategy/liquidity_sweep.py

Detects liquidity sweep / reversal setups using market levels
(PMH/PML/PDH/PDL) and candle features, with QQQ directional
confirmation. Produces a fully specified TradeSignal (entry, stop,
targets) — this module never places or simulates orders; that is the
broker's responsibility.

Bar representation
-------------------
Bars are plain dicts (or any Mapping) with at least the keys:
    "timestamp": datetime
    "open": float
    "high": float
    "low": float
    "close": float
    "volume": float

This keeps the strategy module decoupled from any specific data-loading
implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from src.candle_features import lower_wick_ratio, upper_wick_ratio, volume_spike

Direction = str  # "bullish" | "bearish" | "neutral"


@dataclass
class TradeSignal:
    """A fully specified candidate trade produced by the strategy.

    Attributes:
        symbol: Ticker symbol the signal applies to.
        direction: "long" or "short".
        entry: Proposed entry price (stop/limit above or below the
            rejection candle, per setup direction).
        stop: Proposed stop-loss price.
        targets: Take-profit price levels, e.g. [2.5R price, 3R price].
        risk_per_share: abs(entry - stop), the per-share dollar risk.
        reason_entry: Human-readable justification for the trade,
            written to the trade journal.
        timestamp: Timestamp of the rejection candle that triggered
            the signal.
        swept_level: The specific PMH/PML/PDH/PDL price level that was
            swept and reclaimed to produce this signal.
        swept_level_type: Which level was swept -- "PMH", "PML", "PDH",
            or "PDL" -- diagnostic-only label alongside swept_level.
        wick_ratio: The rejection candle's lower_wick_ratio (long) or
            upper_wick_ratio (short) value that was checked against
            cfg's minimum -- recorded for diagnostics only.
        volume_multiple: bar volume / avg_volume at signal time --
            recorded for diagnostics only (the pass/fail check itself
            already happened via volume_spike()).
        qqq_confirmation: QQQ's classified direction ("bullish" /
            "bearish" / "neutral") used to confirm this signal --
            recorded for diagnostics only.
    """

    symbol: str
    direction: str
    entry: float
    stop: float
    targets: list[float]
    risk_per_share: float
    reason_entry: str
    timestamp: datetime
    swept_level: float
    swept_level_type: str
    wick_ratio: float
    volume_multiple: float
    qqq_confirmation: str


def qqq_direction(qqq_bar: Mapping[str, Any], neutral_band_pct: float = 0.05) -> Direction:
    """Classify QQQ's directional bias from its own bar.

    The move is measured as the percent change from open to close of
    the given bar. Moves within +/- neutral_band_pct are "neutral".

    Args:
        qqq_bar: A bar mapping with at least "open" and "close" keys.
        neutral_band_pct: Percent (e.g. 0.05 for 0.05%) within which a
            move is considered neutral rather than directional.

    Returns:
        "bullish" if close > open beyond the neutral band, "bearish"
        if close < open beyond the neutral band, otherwise "neutral".

    Raises:
        ValueError: If qqq_bar["open"] is zero or negative (cannot
            compute a percent move).
    """
    open_ = qqq_bar["open"]
    close = qqq_bar["close"]
    if open_ <= 0:
        raise ValueError("qqq_bar['open'] must be positive to compute percent move")

    pct_move = (close - open_) / open_ * 100.0

    if pct_move > neutral_band_pct:
        return "bullish"
    if pct_move < -neutral_band_pct:
        return "bearish"
    return "neutral"


def _build_targets(entry: float, risk: float, direction: str, reward_risk_targets: list[float]) -> list[float]:
    """Compute take-profit price levels at each configured R multiple.

    Args:
        entry: Entry price.
        risk: Per-share dollar risk (always positive).
        direction: "long" or "short".
        reward_risk_targets: R multiples, e.g. [2.5, 3.0].

    Returns:
        List of target prices, one per R multiple, in the same order
        as `reward_risk_targets`.
    """
    if direction == "long":
        return [entry + risk * r for r in reward_risk_targets]
    return [entry - risk * r for r in reward_risk_targets]


def detect_long_setup(
    bar: Mapping[str, Any],
    levels: Mapping[str, Any],
    avg_volume: float,
    qqq_dir: Direction,
    cfg: Mapping[str, Any],
    tick: float = 0.01,
) -> TradeSignal | None:
    """Detect a long liquidity-sweep/reversal setup on a single bar.

    Conditions (all must hold):
        1. bar low sweeps below PML or PDL.
        2. bar close reclaims back above the swept level.
        3. lower_wick_ratio(bar) >= cfg["min_lower_wick_ratio"].
        4. volume_spike(bar volume, avg_volume, cfg["min_volume_multiple"]).
        5. qqq_dir in {"bullish", "neutral"}.

    Args:
        bar: The candidate rejection candle.
        levels: Dict with at least "PML" and/or "PDL" (floats; either
            may be None if unavailable).
        avg_volume: Recent average volume baseline for volume_spike().
        qqq_dir: QQQ's classified direction for this bar's timeframe.
        cfg: Strategy config dict with keys "min_lower_wick_ratio",
            "min_volume_multiple", "reward_risk_targets".
        tick: Minimum price increment used to place entry just above
            the rejection candle's high and stop just below its low.

    Returns:
        A TradeSignal if all conditions are met, otherwise None.
    """
    pml = levels.get("PML")
    pdl = levels.get("PDL")
    swept_level = None
    swept_level_type = None
    for level_type, level in (("PML", pml), ("PDL", pdl)):
        if level is not None and bar["low"] < level <= bar["close"]:
            swept_level = level
            swept_level_type = level_type
            break

    if swept_level is None:
        return None

    if qqq_dir not in ("bullish", "neutral"):
        return None

    lwr = lower_wick_ratio(bar["open"], bar["high"], bar["low"], bar["close"])
    if lwr < cfg["min_lower_wick_ratio"]:
        return None

    if not volume_spike(bar["volume"], avg_volume, cfg["min_volume_multiple"]):
        return None

    entry = bar["high"] + tick
    stop = bar["low"] - tick
    risk = entry - stop
    if risk <= 0:
        return None

    targets = _build_targets(entry, risk, "long", cfg["reward_risk_targets"])
    volume_multiple = bar["volume"] / avg_volume if avg_volume else float("nan")

    reason = (
        f"Long liquidity sweep: swept level {swept_level:.2f}, "
        f"reclaimed close {bar['close']:.2f}, lower wick ratio "
        f"{lwr:.2f}, volume {bar['volume']:.0f} vs avg {avg_volume:.0f}, "
        f"QQQ {qqq_dir}"
    )

    return TradeSignal(
        symbol=bar.get("symbol", ""),
        direction="long",
        entry=entry,
        stop=stop,
        targets=targets,
        risk_per_share=risk,
        reason_entry=reason,
        timestamp=bar["timestamp"],
        swept_level=swept_level,
        swept_level_type=swept_level_type,
        wick_ratio=lwr,
        volume_multiple=volume_multiple,
        qqq_confirmation=qqq_dir,
    )


def detect_short_setup(
    bar: Mapping[str, Any],
    levels: Mapping[str, Any],
    avg_volume: float,
    qqq_dir: Direction,
    cfg: Mapping[str, Any],
    tick: float = 0.01,
) -> TradeSignal | None:
    """Detect a short liquidity-sweep/reversal setup on a single bar.

    Mirror image of detect_long_setup, around PMH/PDH with the upper
    wick ratio.

    Args:
        bar: The candidate rejection candle.
        levels: Dict with at least "PMH" and/or "PDH" (floats; either
            may be None if unavailable).
        avg_volume: Recent average volume baseline for volume_spike().
        qqq_dir: QQQ's classified direction for this bar's timeframe.
        cfg: Strategy config dict with keys "min_upper_wick_ratio",
            "min_volume_multiple", "reward_risk_targets".
        tick: Minimum price increment used to place entry just below
            the rejection candle's low and stop just above its high.

    Returns:
        A TradeSignal if all conditions are met, otherwise None.
    """
    pmh = levels.get("PMH")
    pdh = levels.get("PDH")
    swept_level = None
    swept_level_type = None
    for level_type, level in (("PMH", pmh), ("PDH", pdh)):
        if level is not None and bar["high"] > level >= bar["close"]:
            swept_level = level
            swept_level_type = level_type
            break

    if swept_level is None:
        return None

    if qqq_dir not in ("bearish", "neutral"):
        return None

    uwr = upper_wick_ratio(bar["open"], bar["high"], bar["low"], bar["close"])
    if uwr < cfg["min_upper_wick_ratio"]:
        return None

    if not volume_spike(bar["volume"], avg_volume, cfg["min_volume_multiple"]):
        return None

    entry = bar["low"] - tick
    stop = bar["high"] + tick
    risk = stop - entry
    if risk <= 0:
        return None

    targets = _build_targets(entry, risk, "short", cfg["reward_risk_targets"])
    volume_multiple = bar["volume"] / avg_volume if avg_volume else float("nan")

    reason = (
        f"Short liquidity sweep: swept level {swept_level:.2f}, "
        f"reclaimed close {bar['close']:.2f}, upper wick ratio "
        f"{uwr:.2f}, volume {bar['volume']:.0f} vs avg {avg_volume:.0f}, "
        f"QQQ {qqq_dir}"
    )

    return TradeSignal(
        symbol=bar.get("symbol", ""),
        direction="short",
        entry=entry,
        stop=stop,
        targets=targets,
        risk_per_share=risk,
        reason_entry=reason,
        timestamp=bar["timestamp"],
        swept_level=swept_level,
        swept_level_type=swept_level_type,
        wick_ratio=uwr,
        volume_multiple=volume_multiple,
        qqq_confirmation=qqq_dir,
    )


def scan(
    bar: Mapping[str, Any],
    levels: Mapping[str, Any],
    avg_volume: float,
    qqq_dir: Direction,
    cfg: Mapping[str, Any],
    tick: float = 0.01,
) -> TradeSignal | None:
    """Try long detection then short detection; return the first match.

    Args:
        bar: The candidate rejection candle.
        levels: Dict with "PMH", "PML", "PDH", "PDL" keys.
        avg_volume: Recent average volume baseline.
        qqq_dir: QQQ's classified direction for this bar's timeframe.
        cfg: Strategy config dict (see detect_long_setup /
            detect_short_setup for required keys).
        tick: Minimum price increment for entry/stop placement.

    Returns:
        A TradeSignal for the first matching setup (long checked
        first), or None if neither setup matches. A single bar cannot
        match both a long and short setup simultaneously because the
        sweep conditions (low below a support level vs. high above a
        resistance level) and QQQ direction requirements are mutually
        exclusive for non-neutral QQQ readings; in the neutral QQQ case
        both could theoretically be checked, so long is prioritized.
    """
    long_signal = detect_long_setup(bar, levels, avg_volume, qqq_dir, cfg, tick)
    if long_signal is not None:
        return long_signal
    return detect_short_setup(bar, levels, avg_volume, qqq_dir, cfg, tick)
