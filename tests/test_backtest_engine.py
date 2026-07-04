"""
Tests for src/backtesting/engine.py.

Covers both:
  - The full pipeline against the committed synthetic fixture data in
    sample_data/backtest/ (a realistic 3-day dataset: 1 winning trade,
    1 losing trade, and 1 day with no valid setup).
  - Focused, hand-built minimal datasets that isolate individual risk
    rules (max trades/day, max daily loss %, consecutive losses, the
    no-new-trades-after cutoff, and the forced end-of-session flatten)
    from the full sample data, so each rule's behavior is unambiguous.

No network access, no broker connection, and no live trading are
involved anywhere in this file -- everything runs through PaperBroker.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from sample_data.backtest.generate_backtest_data import generate_backtest_bars
from src.backtesting.engine import run_backtest
from src.journal.trade_journal import TradeJournal

TZ = ZoneInfo("America/New_York")
DAY_A = "2026-08-03"  # history-only: establishes Day B's PDH/PDL
DAY_B = "2026-08-04"
DAY_C = "2026-08-05"

WATCHLIST_CFG = {"symbols": ["TST"], "confirmation_symbol": "QQQ"}
PRICE_LOOKUP = {"TST": 100.0}
MARKET_CAP_LOOKUP = {"TST": 1_000_000_000.0}


# ---------------------------------------------------------------------------
# Minimal synthetic bar builders. Every bar is hand-specified (no random
# walk) so entry/stop/target and volume-spike behavior are exact and
# reproducible, using tiny bar counts.
# ---------------------------------------------------------------------------


def _bar(date_str, time_str, o, h, l, c, v):
    return {
        "timestamp": pd.Timestamp(f"{date_str} {time_str}", tz=TZ),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v,
    }


def _history_bar(date_str):
    """Previous day's regular-session bar: PDH=110.0, PDL=90.0."""
    return _bar(date_str, "09:30:00", 100.0, 110.0, 90.0, 100.0, 100)


def _premarket_bar(date_str):
    """Establishes a wide PMH=130.0 / PML=70.0 that won't interfere."""
    return _bar(date_str, "04:00:00", 100.0, 130.0, 70.0, 100.0, 100)


def _long_trigger(date_str, time_str, vol=1000):
    """Sweeps below PDL(90.0), reclaims close=95.0. entry=96.01, stop=84.99."""
    return _bar(date_str, time_str, 95.0, 96.0, 85.0, 95.0, vol)


def _long_win_exit(date_str, time_str, vol=500):
    """High clears the 2.5R target (123.56) for the standard trigger above."""
    return _bar(date_str, time_str, 100.0, 124.0, 99.0, 123.6, vol)


def _long_loss_exit(date_str, time_str, vol=500):
    """Low breaches the stop (84.99) for the standard trigger above."""
    return _bar(date_str, time_str, 90.0, 91.0, 84.0, 84.5, vol)


def _filler(date_str, time_str, vol=50):
    """A flat, low-volume bar: never sweeps a level or spikes volume."""
    return _bar(date_str, time_str, 95.0, 95.2, 94.8, 95.0, vol)


def _qqq_bull(date_str, time_str):
    return _bar(date_str, time_str, 500.0, 501.0, 499.5, 501.0, 5000)


def _frame(rows):
    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


def _settings(tmp_path, **risk_overrides):
    risk_controls = {
        "max_trades_per_day": 10,
        "max_daily_loss_pct": 100.0,
        "max_consecutive_losses": 10,
    }
    risk_controls.update(risk_overrides)
    return {
        "mode": {"trading_mode": "paper", "enable_live_trading": False},
        "session": {
            "timezone": "America/New_York",
            "session_start": "09:35",
            "session_end": "13:00",
            "no_new_trades_after": "12:45",
            "force_flat_time": "13:00",
        },
        "universe_filters": {"min_price": 1.0, "min_market_cap": 0.0},
        "market_levels": {"premarket_start": "04:00", "premarket_end": "09:30"},
        "candle_features": {"volume_lookback_bars": 3, "volume_spike_multiplier": 1.5},
        "strategy": {
            "liquidity_sweep": {
                "min_lower_wick_ratio": 0.5,
                "min_upper_wick_ratio": 0.5,
                "min_volume_multiple": 1.5,
                "reward_risk_targets": [2.5, 3.0],
                "qqq_confirmation": {
                    "long_requires": ["bullish", "neutral"],
                    "short_requires": ["bearish", "neutral"],
                    "neutral_band_pct": 0.05,
                },
            }
        },
        "position_sizing": {"risk_per_trade_pct": 0.333, "max_spread_pct": 0.15, "min_quantity": 1},
        "risk_controls": risk_controls,
        "broker": {"starting_paper_equity": 25_000.0, "commission_per_share": 0.0, "slippage_bps": 0.0},
        "logging": {
            "trade_journal_file": str(tmp_path / "journal.csv"),
            "order_log_file": str(tmp_path / "orders.log"),
        },
    }


def _run(settings, demo_rows, qqq_rows):
    return run_backtest(
        settings=settings,
        watchlist_cfg=WATCHLIST_CFG,
        bars_by_symbol={"TST": _frame(demo_rows)},
        qqq_bars=_frame(qqq_rows),
        price_lookup=PRICE_LOOKUP,
        market_cap_lookup=MARKET_CAP_LOOKUP,
    )


# ---------------------------------------------------------------------------
# Golden-path: the real 3-day sample_data/backtest fixture.
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_bars():
    return generate_backtest_bars()


def _sample_settings(tmp_path):
    from src.config_loader import load_settings

    settings = dict(load_settings("config/settings.yaml"))
    settings["logging"] = dict(settings["logging"])
    settings["logging"]["trade_journal_file"] = str(tmp_path / "journal.csv")
    settings["logging"]["order_log_file"] = str(tmp_path / "orders.log")
    return settings


def test_full_backtest_detects_one_win_one_loss_and_a_no_trade_day(tmp_path, sample_bars):
    stock_bars, qqq_bars = sample_bars
    result = run_backtest(
        settings=_sample_settings(tmp_path),
        watchlist_cfg={"symbols": ["DEMO"], "confirmation_symbol": "QQQ"},
        bars_by_symbol={"DEMO": stock_bars},
        qqq_bars=qqq_bars,
        price_lookup={"DEMO": 150.50},
        market_cap_lookup={"DEMO": 50_000_000_000.0},
    )

    assert len(result.daily_results) == 2  # Day 1 is history-only, not tradable
    day2, day3 = result.daily_results
    assert day2["date"] == "2026-07-01"
    assert day2["trades"] == 2
    assert day3["date"] == "2026-07-02"
    assert day3["trades"] == 0  # no valid setup that day

    assert len(result.trades) == 2
    wins = [t for t in result.trades if t["pnl"] > 0]
    losses = [t for t in result.trades if t["pnl"] <= 0]
    assert len(wins) == 1
    assert len(losses) == 1
    assert wins[0]["reason_exit"] == "target_2.5R"
    assert losses[0]["reason_exit"] == "stop"

    assert result.metrics["total_trades"] == 2
    assert result.metrics["wins"] == 1
    assert result.metrics["losses"] == 1


def test_full_backtest_writes_a_per_trade_journal_csv(tmp_path, sample_bars):
    stock_bars, qqq_bars = sample_bars
    settings = _sample_settings(tmp_path)
    run_backtest(
        settings=settings,
        watchlist_cfg={"symbols": ["DEMO"], "confirmation_symbol": "QQQ"},
        bars_by_symbol={"DEMO": stock_bars},
        qqq_bars=qqq_bars,
        price_lookup={"DEMO": 150.50},
        market_cap_lookup={"DEMO": 50_000_000_000.0},
    )

    journal = TradeJournal(settings["logging"]["trade_journal_file"])
    journal_df = journal.read_all()
    assert len(journal_df) == 2
    assert set(journal_df["direction"]) == {"long", "short"}
    for col in (
        "timestamp", "symbol", "direction", "swept_level", "entry", "stop",
        "target", "risk_amount", "quantity", "exit", "pnl", "reason_entry",
        "reason_exit",
    ):
        assert col in journal_df.columns


# ---------------------------------------------------------------------------
# Focused risk-rule tests on minimal hand-built datasets.
# ---------------------------------------------------------------------------


def test_position_sizing_and_pnl_reflect_configured_risk_per_trade(tmp_path):
    settings = _settings(tmp_path)
    demo_rows = [_history_bar(DAY_A), _premarket_bar(DAY_B), _long_trigger(DAY_B, "09:36:00"), _long_win_exit(DAY_B, "09:37:00")]
    qqq_rows = [_qqq_bull(DAY_B, "09:36:00")]

    result = _run(settings, demo_rows, qqq_rows)

    assert len(result.trades) == 1
    trade = result.trades[0]
    # dollar_risk = 25000 * 0.333% = 83.25; stop_distance = 96.01-84.99 = 11.02
    # quantity = floor(83.25 / 11.02) = 7
    assert trade["quantity"] == 7
    assert trade["pnl"] == pytest.approx((123.56 - 96.01) * 7, abs=0.05)


def test_max_trades_per_day_limits_trades_taken(tmp_path):
    settings = _settings(tmp_path, max_trades_per_day=2)
    demo_rows = [
        _history_bar(DAY_A),
        _premarket_bar(DAY_B),
        _long_trigger(DAY_B, "09:36:00"),
        _long_win_exit(DAY_B, "09:37:00"),
        _filler(DAY_B, "09:38:00"),
        _long_trigger(DAY_B, "09:39:00"),
        _long_win_exit(DAY_B, "09:40:00"),
        _filler(DAY_B, "09:41:00"),
        _long_trigger(DAY_B, "09:42:00"),  # 3rd attempt: must be blocked
    ]
    qqq_rows = [_qqq_bull(DAY_B, t) for t in ("09:36:00", "09:39:00", "09:42:00")]

    result = _run(settings, demo_rows, qqq_rows)

    assert len(result.trades) == 2
    assert result.daily_results[0]["trades"] == 2


def test_max_daily_loss_pct_halts_trading_for_the_rest_of_the_day(tmp_path):
    settings = _settings(tmp_path, max_daily_loss_pct=0.1, max_trades_per_day=10, max_consecutive_losses=10)
    demo_rows = [
        _history_bar(DAY_A),
        _premarket_bar(DAY_B),
        _long_trigger(DAY_B, "09:36:00"),
        _long_loss_exit(DAY_B, "09:37:00"),
        _filler(DAY_B, "09:38:00"),
        _long_trigger(DAY_B, "09:39:00"),  # must be blocked: daily loss cap already breached
    ]
    qqq_rows = [_qqq_bull(DAY_B, t) for t in ("09:36:00", "09:39:00")]

    result = _run(settings, demo_rows, qqq_rows)

    assert len(result.trades) == 1
    assert result.trades[0]["pnl"] < 0


def test_max_consecutive_losses_halts_trading_for_the_rest_of_the_day(tmp_path):
    settings = _settings(tmp_path, max_consecutive_losses=2, max_daily_loss_pct=100.0, max_trades_per_day=10)
    demo_rows = [
        _history_bar(DAY_A),
        _premarket_bar(DAY_B),
        _long_trigger(DAY_B, "09:36:00"),
        _long_loss_exit(DAY_B, "09:37:00"),
        _filler(DAY_B, "09:38:00"),
        _long_trigger(DAY_B, "09:39:00"),
        _long_loss_exit(DAY_B, "09:40:00"),
        _filler(DAY_B, "09:41:00"),
        _long_trigger(DAY_B, "09:42:00"),  # 3rd attempt: must be blocked
    ]
    qqq_rows = [_qqq_bull(DAY_B, t) for t in ("09:36:00", "09:39:00", "09:42:00")]

    result = _run(settings, demo_rows, qqq_rows)

    assert len(result.trades) == 2
    assert all(t["pnl"] < 0 for t in result.trades)


def test_no_new_trades_after_cutoff_blocks_entry(tmp_path):
    settings = _settings(tmp_path)
    demo_rows = [_history_bar(DAY_A), _premarket_bar(DAY_B), _long_trigger(DAY_B, "12:50:00")]
    qqq_rows = [_qqq_bull(DAY_B, "12:50:00")]

    result = _run(settings, demo_rows, qqq_rows)

    assert len(result.trades) == 0


def test_force_exit_by_session_end(tmp_path):
    settings = _settings(tmp_path)
    demo_rows = [
        _history_bar(DAY_A),
        _premarket_bar(DAY_B),
        _long_trigger(DAY_B, "12:40:00"),
        _bar(DAY_B, "13:00:00", 100.0, 101.0, 99.0, 100.0, 100),  # never hits stop/target; forces flat
    ]
    qqq_rows = [_qqq_bull(DAY_B, "12:40:00")]

    result = _run(settings, demo_rows, qqq_rows)

    assert len(result.trades) == 1
    assert result.trades[0]["reason_exit"] == "force_flat"
    assert result.trades[0]["exit"] == pytest.approx(100.0)


def test_day_with_no_valid_setup_produces_zero_trades(tmp_path):
    settings = _settings(tmp_path)
    demo_rows = [
        _history_bar(DAY_A),
        _premarket_bar(DAY_B),
        _filler(DAY_B, "09:36:00"),
        _filler(DAY_B, "09:37:00"),
        _filler(DAY_B, "09:38:00"),
    ]
    qqq_rows = [_qqq_bull(DAY_B, "09:36:00"), _qqq_bull(DAY_B, "09:37:00"), _qqq_bull(DAY_B, "09:38:00")]

    result = _run(settings, demo_rows, qqq_rows)

    assert len(result.trades) == 0
    assert result.daily_results[0]["trades"] == 0
    assert result.metrics["total_trades"] == 0


def test_risk_state_resets_for_a_new_trading_day(tmp_path):
    settings = _settings(tmp_path, max_consecutive_losses=2, max_daily_loss_pct=100.0, max_trades_per_day=10)
    demo_rows = [
        _history_bar(DAY_A),
        _premarket_bar(DAY_B),
        _long_trigger(DAY_B, "09:36:00"),
        _long_loss_exit(DAY_B, "09:37:00"),
        _filler(DAY_B, "09:38:00"),
        _long_trigger(DAY_B, "09:39:00"),
        _long_loss_exit(DAY_B, "09:40:00"),
        _filler(DAY_B, "09:41:00"),
        _long_trigger(DAY_B, "09:42:00"),  # blocked: 2 consecutive losses already hit
        _premarket_bar(DAY_C),
        _filler(DAY_C, "09:35:00"),
        # Fresh long setup on Day C, sweeping Day B's realized low (~84.0):
        _bar(DAY_C, "09:36:00", 88.0, 91.0, 60.0, 90.0, 1000),
        _bar(DAY_C, "09:37:00", 100.0, 169.0, 90.0, 168.0, 500),  # wins
    ]
    qqq_rows = [
        _qqq_bull(DAY_B, "09:36:00"),
        _qqq_bull(DAY_B, "09:39:00"),
        _qqq_bull(DAY_B, "09:42:00"),
        _qqq_bull(DAY_C, "09:36:00"),
    ]

    result = _run(settings, demo_rows, qqq_rows)

    assert len(result.daily_results) == 2
    day_b, day_c = result.daily_results
    assert day_b["trades"] == 2  # halted after 2 consecutive losses
    assert day_c["trades"] == 1  # fresh day: risk state reset, new trade allowed

    assert len(result.trades) == 3
    assert result.trades[-1]["pnl"] > 0


def test_no_live_broker_class_exists_anywhere_in_the_backtest_path():
    """Guard test: confirm the backtester only ever exercises PaperBroker."""
    import src.backtesting.engine as engine_module
    import src.broker.paper_broker as broker_module

    assert not hasattr(broker_module, "LiveBroker")
    assert not hasattr(engine_module, "LiveBroker")
    assert "PaperBroker" in dir(engine_module)
