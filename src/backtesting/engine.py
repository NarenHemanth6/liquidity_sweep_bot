"""
backtesting/engine.py

Runs the liquidity sweep strategy across multiple historical trading
days, using PaperBroker for every simulated fill. This is the ONLY
execution path in this module.

Explicit safety notes
----------------------
- No network I/O, no broker connection, and no credentials of any kind
  are used anywhere in this file.
- Every fill is simulated by src.broker.paper_broker.PaperBroker, the
  only broker implementation in this codebase. There is no LiveBroker
  class anywhere.
- This module refuses to run unless settings["mode"]["trading_mode"]
  == "paper" (see `LiveTradingDisabledError` / `_enforce_paper_mode`).

Day-by-day semantics
---------------------
Each historical trading day is treated as an independent session for
risk-control purposes: RiskManager is reset at the start of every day
(so max trades/day, max daily loss %, and consecutive-loss limits all
apply per day), while account equity compounds continuously across the
whole backtest through a single shared PaperBroker instance.

The earliest calendar date present in `bars_by_symbol` is used purely
as history (it establishes the first tradable day's PDH/PDL) and is
never itself scanned for trade signals — this mirrors
src.market_levels.MarketLevels.previous_day_high_low, which needs at
least one prior day of regular-session bars.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from src.backtesting.metrics import compute_metrics
from src.broker.paper_broker import PaperBroker, Position
from src.candle_features import rolling_average_volume, volume_spike
from src.journal.trade_journal import TradeJournal
from src.market_levels import MarketLevels
from src.risk.position_sizing import calculate_position_size
from src.risk.risk_controls import RiskManager
from src.strategy.liquidity_sweep import qqq_direction, scan
from src.watchlist import Watchlist


class LiveTradingDisabledError(RuntimeError):
    """Raised when the backtester is asked to run outside paper mode."""


def _enforce_paper_mode(settings: dict[str, Any]) -> None:
    """Guard clause: refuse to proceed unless strictly in paper mode.

    Args:
        settings: Settings dict (see src.config_loader.load_settings).

    Raises:
        LiveTradingDisabledError: If settings["mode"]["trading_mode"]
            is not "paper".
    """
    trading_mode = settings.get("mode", {}).get("trading_mode")
    if trading_mode != "paper":
        raise LiveTradingDisabledError(
            f"Refusing to backtest: mode.trading_mode is '{trading_mode}', "
            f"but this build only supports 'paper'. There is no live "
            f"broker implementation anywhere in this codebase."
        )


def _build_watchlist(settings: dict[str, Any], watchlist_cfg: dict[str, Any]) -> Watchlist:
    """Construct a Watchlist instance from loaded config."""
    filters = settings["universe_filters"]
    return Watchlist(
        candidates=list(watchlist_cfg["symbols"]),
        confirmation_symbol=watchlist_cfg["confirmation_symbol"],
        min_price=filters["min_price"],
        min_market_cap=filters["min_market_cap"],
    )


def _build_risk_cfg(settings: dict[str, Any]) -> dict[str, Any]:
    """Assemble the RiskManager config dict from settings.yaml sections."""
    risk_cfg = dict(settings["risk_controls"])
    risk_cfg["no_new_trades_after"] = settings["session"]["no_new_trades_after"]
    risk_cfg["force_flat_time"] = settings["session"]["force_flat_time"]
    risk_cfg["timezone"] = settings["session"]["timezone"]
    return risk_cfg


def _trading_dates(bars_by_symbol: dict[str, pd.DataFrame], timezone: str) -> list[date]:
    """Return every distinct calendar date present across all symbols.

    Args:
        bars_by_symbol: Mapping of symbol -> OHLCV DataFrame.
        timezone: IANA timezone used to localize timestamps before
            taking their date component.

    Returns:
        Sorted ascending list of unique dates.
    """
    all_dates: set[date] = set()
    for bars in bars_by_symbol.values():
        if bars is None or bars.empty:
            continue
        local_ts = bars["timestamp"].dt.tz_convert(timezone)
        all_dates.update(local_ts.dt.date.unique())
    return sorted(all_dates)


def _bar_dict(symbol: str, row: pd.Series) -> dict[str, Any]:
    """Build the plain-dict bar representation expected by strategy/broker code."""
    return {
        "symbol": symbol,
        "timestamp": row["timestamp"],
        "open": row["open"],
        "high": row["high"],
        "low": row["low"],
        "close": row["close"],
        "volume": row["volume"],
    }


@dataclass
class BacktestResult:
    """Full result of a multi-day historical backtest.

    Attributes:
        tradable_symbols: Symbols that passed the universe filters.
        trades: Every closed trade record, in chronological order.
        equity_curve: Account equity after the starting balance and
            after every closed trade (for drawdown/plotting).
        daily_results: One summary dict per tradable day: "date",
            "trades" (count that day), "ending_equity".
        metrics: Aggregate performance metrics; see
            src.backtesting.metrics.compute_metrics.
    """

    tradable_symbols: list[str]
    trades: list[dict[str, Any]]
    equity_curve: list[float]
    daily_results: list[dict[str, Any]]
    metrics: dict[str, Any]


def run_backtest(
    settings: dict[str, Any],
    watchlist_cfg: dict[str, Any],
    bars_by_symbol: dict[str, pd.DataFrame],
    qqq_bars: pd.DataFrame,
    price_lookup: dict[str, float],
    market_cap_lookup: dict[str, float],
    overwrite_journal: bool = True,
) -> BacktestResult:
    """Run a multi-day historical backtest of the liquidity sweep strategy.

    For every tradable day (every calendar date present except the
    earliest, which is history-only), this: computes market levels and
    the volume baseline from all bars up to and including that day,
    resets the RiskManager for a fresh day, then walks each tradable
    symbol's bars within the session window (session_start..session_end)
    in chronological order — managing any open position first (force-
    flattening at/after force_flat_time, otherwise checking stop/target),
    and otherwise scanning for a new liquidity-sweep signal, sizing it,
    checking risk controls, and submitting a simulated bracket order via
    PaperBroker.

    Args:
        settings: Loaded settings.yaml-shaped dict (mode, session,
            universe_filters, market_levels, candle_features, strategy,
            position_sizing, risk_controls, broker, logging).
        watchlist_cfg: Dict with "symbols" (list[str]) and
            "confirmation_symbol" (str).
        bars_by_symbol: Mapping of tradable symbol -> OHLCV DataFrame
            (tz-aware timestamps; premarket + regular-session bars for
            every day, plus at least one prior day for PDH/PDL).
        qqq_bars: OHLCV DataFrame for the confirmation symbol, aligned
            in time to `bars_by_symbol`.
        price_lookup: Mapping of symbol -> current price, for watchlist
            filtering.
        market_cap_lookup: Mapping of symbol -> market cap, for
            watchlist filtering.
        overwrite_journal: If True (the default), the per-trade journal
            file starts empty at the beginning of this run -- so every
            backtest run reports only its own trades, not trades
            accumulated from previous runs against the same journal
            path. Pass False to append to an existing journal file
            instead (explicit opt-in).

    Returns:
        A BacktestResult with every closed trade, the equity curve,
        per-day summaries, and aggregate metrics.

    Raises:
        LiveTradingDisabledError: If the safety gate fails (delegated
            to `_enforce_paper_mode`).
    """
    _enforce_paper_mode(settings)

    watchlist = _build_watchlist(settings, watchlist_cfg)
    tradable = watchlist.refresh(price_lookup, market_cap_lookup)

    broker_cfg = settings["broker"]
    log_cfg = settings["logging"]
    broker = PaperBroker(
        starting_equity=broker_cfg["starting_paper_equity"],
        commission_per_share=broker_cfg.get("commission_per_share", 0.0),
        slippage_bps=broker_cfg.get("slippage_bps", 0.0),
        order_log_path=log_cfg.get("order_log_file", "logs/backtest_orders.log"),
    )
    journal = TradeJournal(
        log_cfg.get("trade_journal_file", "logs/backtest_trade_journal.csv"), overwrite=overwrite_journal
    )

    tz = settings["session"]["timezone"]
    session_start = settings["session"]["session_start"]
    session_end = settings["session"]["session_end"]
    levels_engine = MarketLevels(
        timezone=tz,
        premarket_start=settings["market_levels"]["premarket_start"],
        premarket_end=settings["market_levels"]["premarket_end"],
    )

    strategy_cfg = settings["strategy"]["liquidity_sweep"]
    sizing_cfg = settings["position_sizing"]
    vol_lookback = settings["candle_features"]["volume_lookback_bars"]
    vol_multiplier = settings["candle_features"]["volume_spike_multiplier"]
    neutral_band = strategy_cfg["qqq_confirmation"]["neutral_band_pct"]
    risk_cfg = _build_risk_cfg(settings)

    trade_records: list[dict[str, Any]] = []
    equity_curve: list[float] = [broker.equity]
    daily_results: list[dict[str, Any]] = []

    all_dates = _trading_dates(bars_by_symbol, tz)
    tradable_dates = all_dates[1:]

    for day in tradable_dates:
        risk_manager = RiskManager(risk_cfg, starting_equity=broker.equity)
        open_positions: dict[str, Position] = {}
        trades_before = len(trade_records)

        for symbol in tradable:
            bars = bars_by_symbol.get(symbol)
            if bars is None or bars.empty:
                continue

            local_ts_full = bars["timestamp"].dt.tz_convert(tz)
            bars_upto_day = bars.loc[local_ts_full.dt.date <= day].reset_index(drop=True)
            if bars_upto_day.empty:
                continue

            try:
                levels = levels_engine.compute_all(bars_upto_day)
            except ValueError:
                # e.g. no premarket bars for `day` yet -- skip this
                # symbol for today rather than aborting the backtest.
                continue

            avg_volume_series = rolling_average_volume(bars_upto_day["volume"], lookback=vol_lookback)
            local_ts = bars_upto_day["timestamp"].dt.tz_convert(tz)
            time_of_day = local_ts.dt.strftime("%H:%M")
            in_session = (time_of_day >= session_start) & (time_of_day <= session_end)
            session_mask = (local_ts.dt.date == day) & in_session
            session_positions = bars_upto_day.index[session_mask]

            for idx in session_positions:
                bar_row = bars_upto_day.iloc[idx]
                bar = _bar_dict(symbol, bar_row)
                now = bar["timestamp"]

                position = open_positions.get(symbol)
                if position is not None:
                    if risk_manager.should_force_flat(now):
                        record = broker.force_close(position, bar)
                        journal.record_trade(record)
                        risk_manager.register_trade_result(record["pnl"])
                        trade_records.append(record)
                        equity_curve.append(broker.equity)
                        del open_positions[symbol]
                        continue

                    record = broker.process_bar(position, bar)
                    if record is not None:
                        journal.record_trade(record)
                        risk_manager.register_trade_result(record["pnl"])
                        trade_records.append(record)
                        equity_curve.append(broker.equity)
                        del open_positions[symbol]
                    continue

                allowed, _reason = risk_manager.can_open_new_trade(now)
                if not allowed:
                    continue

                avg_volume = avg_volume_series.iloc[idx]
                if pd.isna(avg_volume) or not volume_spike(bar["volume"], avg_volume, vol_multiplier):
                    continue

                qqq_row_matches = qqq_bars[qqq_bars["timestamp"] == now]
                if qqq_row_matches.empty:
                    continue
                qqq_bar = qqq_row_matches.iloc[0].to_dict()
                qqq_dir = qqq_direction(qqq_bar, neutral_band_pct=neutral_band)

                signal = scan(bar, levels, avg_volume, qqq_dir, strategy_cfg)
                if signal is None:
                    continue

                sizing = calculate_position_size(
                    account_equity=broker.equity,
                    entry=signal.entry,
                    stop=signal.stop,
                    risk_per_trade_pct=sizing_cfg["risk_per_trade_pct"],
                    min_quantity=sizing_cfg["min_quantity"],
                )
                if not sizing.approved:
                    continue

                position = broker.submit_bracket_order(signal, sizing.quantity)
                open_positions[symbol] = position

        daily_results.append(
            {
                "date": str(day),
                "trades": len(trade_records) - trades_before,
                "ending_equity": broker.equity,
            }
        )

    metrics = compute_metrics(trade_records, starting_equity=equity_curve[0])

    return BacktestResult(
        tradable_symbols=tradable,
        trades=trade_records,
        equity_curve=equity_curve,
        daily_results=daily_results,
        metrics=metrics,
    )
