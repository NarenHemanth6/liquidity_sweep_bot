"""Tests for src/candle_features.py"""

from __future__ import annotations

import pandas as pd
import pytest

from src.candle_features import (
    body_size,
    candle_range,
    close_location_value,
    lower_wick_ratio,
    rolling_average_volume,
    upper_wick_ratio,
    volume_spike,
)


def test_candle_range_basic():
    assert candle_range(high=105.0, low=100.0) == 5.0


def test_body_size_basic():
    assert body_size(open_=100.0, close=103.0) == 3.0
    assert body_size(open_=103.0, close=100.0) == 3.0


def test_lower_wick_ratio_hammer():
    # Hammer: opens near high, dips low, closes near high.
    # open=104, high=105, low=95, close=104 -> lower wick large
    ratio = lower_wick_ratio(open_=104.0, high=105.0, low=95.0, close=104.0)
    # min(open, close) = 104, low = 95, range = 10 -> (104-95)/10 = 0.9
    assert ratio == pytest.approx(0.9)


def test_upper_wick_ratio_inverted_hammer():
    # Inverted hammer: opens near low, spikes high, closes near low.
    ratio = upper_wick_ratio(open_=100.0, high=110.0, low=99.0, close=100.5)
    # high - max(open, close) = 110 - 100.5 = 9.5; range = 11
    assert ratio == pytest.approx(9.5 / 11.0)


def test_wick_ratios_zero_range_no_error():
    # Doji with high == low must not raise ZeroDivisionError.
    assert lower_wick_ratio(100.0, 100.0, 100.0, 100.0) == 0.0
    assert upper_wick_ratio(100.0, 100.0, 100.0, 100.0) == 0.0


def test_close_location_value_at_high():
    clv = close_location_value(open_=100.0, high=110.0, low=100.0, close=110.0)
    assert clv == pytest.approx(1.0)


def test_close_location_value_at_low():
    clv = close_location_value(open_=110.0, high=110.0, low=100.0, close=100.0)
    assert clv == pytest.approx(-1.0)


def test_close_location_value_at_midpoint():
    clv = close_location_value(open_=100.0, high=110.0, low=100.0, close=105.0)
    assert clv == pytest.approx(0.0)


def test_close_location_value_zero_range():
    assert close_location_value(100.0, 100.0, 100.0, 100.0) == 0.0


def test_volume_spike_boundary_exactly_at_multiplier():
    # exactly 1.5x should count as a spike (>=)
    assert volume_spike(current_volume=1500, avg_volume=1000, multiplier=1.5) is True


def test_volume_spike_below_multiplier():
    assert volume_spike(current_volume=1499, avg_volume=1000, multiplier=1.5) is False


def test_volume_spike_zero_avg_volume():
    assert volume_spike(current_volume=1000, avg_volume=0, multiplier=1.5) is False


def test_rolling_average_volume_matches_hand_computed():
    volumes = pd.Series([10, 20, 30, 40, 50])
    result = rolling_average_volume(volumes, lookback=3)
    # first two entries NaN, then (10+20+30)/3=20, (20+30+40)/3=30, (30+40+50)/3=40
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == pytest.approx(20.0)
    assert result.iloc[3] == pytest.approx(30.0)
    assert result.iloc[4] == pytest.approx(40.0)
