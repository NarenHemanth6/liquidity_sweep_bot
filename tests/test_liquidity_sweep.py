"""Tests for src/strategy/liquidity_sweep.py"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.strategy.liquidity_sweep import (
    detect_long_setup,
    detect_short_setup,
    qqq_direction,
    scan,
)

CFG = {
    "min_lower_wick_ratio": 0.50,
    "min_upper_wick_ratio": 0.50,
    "min_volume_multiple": 1.5,
    "reward_risk_targets": [2.5, 3.0],
}

TS = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)


def make_long_bar(**overrides):
    bar = {
        "symbol": "AAPL",
        "timestamp": TS,
        "open": 104.0,
        "high": 105.0,
        "low": 95.0,   # sweeps below PML=97
        "close": 104.0,  # reclaims above 97
        "volume": 2000,
    }
    bar.update(overrides)
    return bar


def make_short_bar(**overrides):
    bar = {
        "symbol": "AAPL",
        "timestamp": TS,
        "open": 100.0,
        "high": 115.0,  # sweeps above PMH=110
        "low": 99.5,
        "close": 100.5,  # reclaims below 110
        "volume": 2000,
    }
    bar.update(overrides)
    return bar


LEVELS_LONG = {"PML": 97.0, "PDL": None, "PMH": None, "PDH": None}
LEVELS_SHORT = {"PMH": 110.0, "PDH": None, "PML": None, "PDL": None}


def test_detect_long_setup_fires_with_valid_conditions():
    bar = make_long_bar()
    signal = detect_long_setup(bar, LEVELS_LONG, avg_volume=1000, qqq_dir="bullish", cfg=CFG)
    assert signal is not None
    assert signal.direction == "long"
    assert signal.symbol == "AAPL"
    assert signal.entry == pytest.approx(bar["high"] + 0.01)
    assert signal.stop == pytest.approx(bar["low"] - 0.01)
    risk = signal.entry - signal.stop
    assert signal.targets[0] == pytest.approx(signal.entry + risk * 2.5)
    assert signal.targets[1] == pytest.approx(signal.entry + risk * 3.0)


def test_detect_long_setup_fails_low_wick_ratio():
    # Body takes up almost the whole range -> low lower-wick ratio.
    # Still sweeps below PML=97 and reclaims above it, but the wick is small.
    bar = make_long_bar(open=95.5, low=95.0, high=105.0, close=104.5)
    signal = detect_long_setup(bar, LEVELS_LONG, avg_volume=1000, qqq_dir="bullish", cfg=CFG)
    assert signal is None


def test_detect_long_setup_fails_low_volume():
    bar = make_long_bar(volume=1000)  # avg=1000, needs >= 1500
    signal = detect_long_setup(bar, LEVELS_LONG, avg_volume=1000, qqq_dir="bullish", cfg=CFG)
    assert signal is None


def test_detect_long_setup_fails_bearish_qqq():
    bar = make_long_bar()
    signal = detect_long_setup(bar, LEVELS_LONG, avg_volume=1000, qqq_dir="bearish", cfg=CFG)
    assert signal is None


def test_detect_short_setup_fires_with_valid_conditions():
    bar = make_short_bar()
    signal = detect_short_setup(bar, LEVELS_SHORT, avg_volume=1000, qqq_dir="bearish", cfg=CFG)
    assert signal is not None
    assert signal.direction == "short"
    assert signal.entry == pytest.approx(bar["low"] - 0.01)
    assert signal.stop == pytest.approx(bar["high"] + 0.01)
    risk = signal.stop - signal.entry
    assert signal.targets[0] == pytest.approx(signal.entry - risk * 2.5)


def test_detect_short_setup_fails_low_upper_wick_ratio():
    # Still sweeps above PMH=110 and reclaims below it, but the body
    # dominates the range so the upper wick ratio is small.
    bar = make_short_bar(open=100.0, high=111.0, low=99.5, close=109.9)
    signal = detect_short_setup(bar, LEVELS_SHORT, avg_volume=1000, qqq_dir="bearish", cfg=CFG)
    assert signal is None


def test_detect_short_setup_fails_bullish_qqq():
    bar = make_short_bar()
    signal = detect_short_setup(bar, LEVELS_SHORT, avg_volume=1000, qqq_dir="bullish", cfg=CFG)
    assert signal is None


def test_scan_returns_none_when_neither_setup_matches():
    # A calm bar that sweeps nothing.
    bar = {
        "symbol": "AAPL",
        "timestamp": TS,
        "open": 100.0,
        "high": 101.0,
        "low": 99.5,
        "close": 100.5,
        "volume": 500,
    }
    levels = {"PML": 90.0, "PDL": 89.0, "PMH": 120.0, "PDH": 121.0}
    result = scan(bar, levels, avg_volume=1000, qqq_dir="neutral", cfg=CFG)
    assert result is None


def test_qqq_direction_classification():
    bullish_bar = {"open": 100.0, "close": 100.20}   # +0.20% > 0.05%
    bearish_bar = {"open": 100.0, "close": 99.80}    # -0.20% < -0.05%
    neutral_bar = {"open": 100.0, "close": 100.02}   # +0.02% within band

    assert qqq_direction(bullish_bar, neutral_band_pct=0.05) == "bullish"
    assert qqq_direction(bearish_bar, neutral_band_pct=0.05) == "bearish"
    assert qqq_direction(neutral_bar, neutral_band_pct=0.05) == "neutral"


def test_qqq_direction_at_exact_boundary_is_neutral():
    # Exactly at the neutral band edge should NOT count as directional
    # (strict > / < comparison).
    boundary_bar = {"open": 100.0, "close": 100.05}
    assert qqq_direction(boundary_bar, neutral_band_pct=0.05) == "neutral"
