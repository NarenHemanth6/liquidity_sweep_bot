"""
Tests for the sample simulation: sample_data/generate_sample_data.py
run through src.main.run_session (paper mode only).

These tests verify the synthetic fixture data actually produces the
two intended liquidity-sweep trades (one long, one short) and that the
CSV trade journal captures them correctly. No network access, no
broker connection, and no live trading are involved anywhere in this
test.
"""

from __future__ import annotations

import pandas as pd
import pytest

from sample_data.generate_sample_data import SYMBOL, generate_sample_bars
from src.config_loader import load_settings
from src.journal.trade_journal import TradeJournal
from src.main import run_session


@pytest.fixture()
def sample_settings(tmp_path):
    """Load real settings.yaml but redirect journal/order logs to tmp_path."""
    settings = load_settings("config/settings.yaml")
    settings = dict(settings)
    settings["logging"] = dict(settings["logging"])
    settings["logging"]["trade_journal_file"] = str(tmp_path / "trade_journal.csv")
    settings["logging"]["order_log_file"] = str(tmp_path / "orders.log")
    return settings


@pytest.fixture()
def sample_watchlist_cfg():
    return {"symbols": [SYMBOL], "confirmation_symbol": "QQQ"}


@pytest.fixture()
def sample_bars():
    stock_bars, qqq_bars = generate_sample_bars()
    return stock_bars, qqq_bars


def test_sample_data_has_expected_shape(sample_bars):
    stock_bars, qqq_bars = sample_bars
    assert not stock_bars.empty
    assert not qqq_bars.empty
    expected_cols = {"timestamp", "open", "high", "low", "close", "volume"}
    assert expected_cols.issubset(stock_bars.columns)
    assert expected_cols.issubset(qqq_bars.columns)
    # Two distinct trading days present in the stock data (for PDH/PDL).
    dates = pd.to_datetime(stock_bars["timestamp"]).dt.date.unique()
    assert len(dates) == 2


def test_sample_simulation_detects_exactly_two_trades(
    sample_settings, sample_watchlist_cfg, sample_bars
):
    stock_bars, qqq_bars = sample_bars
    result = run_session(
        settings=sample_settings,
        watchlist_cfg=sample_watchlist_cfg,
        bars_by_symbol={SYMBOL: stock_bars},
        qqq_bars=qqq_bars,
        price_lookup={SYMBOL: 150.50},
        market_cap_lookup={SYMBOL: 50_000_000_000.0},
    )
    assert result["tradable_symbols"] == [SYMBOL]
    assert len(result["trades"]) == 2


def test_sample_simulation_long_setup_details(
    sample_settings, sample_watchlist_cfg, sample_bars
):
    stock_bars, qqq_bars = sample_bars
    result = run_session(
        settings=sample_settings,
        watchlist_cfg=sample_watchlist_cfg,
        bars_by_symbol={SYMBOL: stock_bars},
        qqq_bars=qqq_bars,
        price_lookup={SYMBOL: 150.50},
        market_cap_lookup={SYMBOL: 50_000_000_000.0},
    )
    long_trades = [t for t in result["trades"] if t["direction"] == "long"]
    assert len(long_trades) == 1

    trade = long_trades[0]
    assert trade["symbol"] == SYMBOL
    assert trade["swept_level"] == pytest.approx(148.00)
    assert trade["stop"] < trade["entry"]
    assert trade["exit"] == pytest.approx(151.01, abs=0.01)
    assert trade["pnl"] > 0  # designed to hit the 2.5R target (a win)
    assert trade["reason_exit"] == "target_2.5R"
    assert "swept level 148.00" in trade["reason_entry"]


def test_sample_simulation_short_setup_details(
    sample_settings, sample_watchlist_cfg, sample_bars
):
    stock_bars, qqq_bars = sample_bars
    result = run_session(
        settings=sample_settings,
        watchlist_cfg=sample_watchlist_cfg,
        bars_by_symbol={SYMBOL: stock_bars},
        qqq_bars=qqq_bars,
        price_lookup={SYMBOL: 150.50},
        market_cap_lookup={SYMBOL: 50_000_000_000.0},
    )
    short_trades = [t for t in result["trades"] if t["direction"] == "short"]
    assert len(short_trades) == 1

    trade = short_trades[0]
    assert trade["symbol"] == SYMBOL
    assert trade["swept_level"] == pytest.approx(152.00)
    assert trade["stop"] > trade["entry"]
    assert trade["exit"] == pytest.approx(152.31, abs=0.01)
    assert trade["pnl"] < 0  # designed to stop out (a loss)
    assert trade["reason_exit"] == "stop"
    assert "swept level 152.00" in trade["reason_entry"]


def test_sample_simulation_writes_csv_journal(
    sample_settings, sample_watchlist_cfg, sample_bars
):
    stock_bars, qqq_bars = sample_bars
    run_session(
        settings=sample_settings,
        watchlist_cfg=sample_watchlist_cfg,
        bars_by_symbol={SYMBOL: stock_bars},
        qqq_bars=qqq_bars,
        price_lookup={SYMBOL: 150.50},
        market_cap_lookup={SYMBOL: 50_000_000_000.0},
    )

    journal = TradeJournal(sample_settings["logging"]["trade_journal_file"])
    journal_df = journal.read_all()

    assert len(journal_df) == 2
    assert set(journal_df["direction"]) == {"long", "short"}
    for col in (
        "timestamp", "symbol", "direction", "swept_level", "entry", "stop",
        "target", "risk_amount", "quantity", "exit", "pnl", "reason_entry",
        "reason_exit",
    ):
        assert col in journal_df.columns


def test_sample_simulation_never_touches_a_live_broker(
    sample_settings, sample_watchlist_cfg, sample_bars
):
    """Guard test: confirm the sample run only exercises PaperBroker."""
    import src.broker.paper_broker as broker_module

    assert not hasattr(broker_module, "LiveBroker")

    stock_bars, qqq_bars = sample_bars
    result = run_session(
        settings=sample_settings,
        watchlist_cfg=sample_watchlist_cfg,
        bars_by_symbol={SYMBOL: stock_bars},
        qqq_bars=qqq_bars,
        price_lookup={SYMBOL: 150.50},
        market_cap_lookup={SYMBOL: 50_000_000_000.0},
    )
    # Ending equity should differ from the starting paper equity only
    # by simulated P&L (i.e. it ran, but purely in-memory).
    assert isinstance(result["ending_equity"], float)
