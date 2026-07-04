"""
candle_features.py

Pure, stateless functions that compute per-candle features used by the
liquidity sweep strategy. Each function is independently unit-testable
and takes plain scalar/Series inputs rather than a specific dataframe
schema, so they can be reused anywhere a single OHLCV bar (or a Series
of them) is available.
"""

from __future__ import annotations

import pandas as pd


def candle_range(high: float, low: float) -> float:
    """Return the high-low range of a candle.

    Args:
        high: Candle high price.
        low: Candle low price.

    Returns:
        high - low. Never negative for valid OHLC data.
    """
    return high - low


def body_size(open_: float, close: float) -> float:
    """Return the absolute size of the candle body.

    Args:
        open_: Candle open price.
        close: Candle close price.

    Returns:
        abs(close - open_).
    """
    return abs(close - open_)


def upper_wick_ratio(open_: float, high: float, low: float, close: float) -> float:
    """Return the fraction of the candle range occupied by the upper wick.

    Defined as (high - max(open, close)) / (high - low). This is high
    for bearish rejection candles (shooting star / inverted hammer at
    resistance) where price spiked up and sold off.

    Args:
        open_: Candle open price.
        high: Candle high price.
        low: Candle low price.
        close: Candle close price.

    Returns:
        A ratio in [0, 1]. Returns 0.0 if the candle has zero range
        (high == low) to avoid division by zero.
    """
    rng = candle_range(high, low)
    if rng <= 0:
        return 0.0
    return (high - max(open_, close)) / rng


def lower_wick_ratio(open_: float, high: float, low: float, close: float) -> float:
    """Return the fraction of the candle range occupied by the lower wick.

    Defined as (min(open, close) - low) / (high - low). This is high
    for bullish rejection candles (hammer at support) where price spiked
    down and was bought back up.

    Args:
        open_: Candle open price.
        high: Candle high price.
        low: Candle low price.
        close: Candle close price.

    Returns:
        A ratio in [0, 1]. Returns 0.0 if the candle has zero range
        (high == low) to avoid division by zero.
    """
    rng = candle_range(high, low)
    if rng <= 0:
        return 0.0
    return (min(open_, close) - low) / rng


def close_location_value(open_: float, high: float, low: float, close: float) -> float:
    """Return the Close Location Value (CLV) of a candle.

    CLV = ((close - low) - (high - close)) / (high - low)

    A value of +1.0 means the candle closed at its high; -1.0 means it
    closed at its low; 0.0 means it closed at the midpoint.

    Args:
        open_: Candle open price (unused in the formula but kept for a
            consistent OHLC signature across this module's functions).
        high: Candle high price.
        low: Candle low price.
        close: Candle close price.

    Returns:
        A value in [-1, 1]. Returns 0.0 if the candle has zero range.
    """
    rng = candle_range(high, low)
    if rng <= 0:
        return 0.0
    return ((close - low) - (high - close)) / rng


def volume_spike(current_volume: float, avg_volume: float, multiplier: float = 1.5) -> bool:
    """Determine whether current volume qualifies as a volume spike.

    Args:
        current_volume: Volume of the candle being evaluated.
        avg_volume: Recent average (baseline) volume, e.g. a rolling mean.
        multiplier: Threshold multiple of avg_volume required to count as
            a spike. Defaults to 1.5x.

    Returns:
        True if current_volume >= avg_volume * multiplier. False if
        avg_volume is zero or negative (no meaningful baseline).
    """
    if avg_volume <= 0:
        return False
    return current_volume >= avg_volume * multiplier


def rolling_average_volume(volumes: pd.Series, lookback: int = 20) -> pd.Series:
    """Compute a simple rolling mean of volume, used as the volume-spike
    baseline ("recent average volume").

    Args:
        volumes: Series of per-bar volumes, in chronological order.
        lookback: Number of bars in the rolling window. Defaults to 20.

    Returns:
        A pandas Series of the same length and index as `volumes`,
        containing the rolling mean. The first `lookback - 1` entries
        will be NaN (insufficient history), consistent with
        pandas' default rolling-window behavior.
    """
    return volumes.rolling(window=lookback, min_periods=lookback).mean()
