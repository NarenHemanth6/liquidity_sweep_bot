"""
main.py

Entry point that wires together config, watchlist, market levels,
strategy, risk controls, position sizing, the paper broker, and the
trade journal into a single simulated trading session.

Safety gate
------------
This module will refuse to run in anything other than paper/simulation
mode:
    - It requires settings.yaml -> mode.trading_mode == "paper".
    - It calls config_loader.is_live_trading_enabled() and refuses to
      start if that returns True.
    - There is no live broker implementation anywhere in this
      codebase (see src/broker/paper_broker.py), so even if both flags
      were somehow set, nothing here could place a real order. The
      check below is a defensive belt-and-suspenders guard for the
      future, not a workaround for a capability that exists today.

Data feed note (v1 scope)
---------------------------
v1 does not include a live/real-time market data connector. `run_session`
operates on OHLCV bars supplied by the caller (e.g. loaded from local
CSV files for paper/backtest-style runs). Running this file directly
with no bars configured will perform the safety checks, wire up all
components, and then report that no data source is configured yet,
rather than attempting any network access.
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

import pandas as pd

from src.broker.paper_broker import PaperBroker, Position
from src.candle_features import rolling_average_volume, volume_spike
from src.config_loader import is_live_trading_enabled, load_settings, load_watchlist
from src.journal.trade_journal import TradeJournal
from src.market_levels import MarketLevels
from src.risk.position_sizing import calculate_position_size
from src.risk.risk_controls import RiskManager
from src.strategy.liquidity_sweep import qqq_direction, scan
from src.watchlist import Watchlist


class LiveTradingDisabledError(RuntimeError):
    """Raised when the app is configured or asked to run outside paper mode."""


def enforce_paper_mode(settings: dict[str, Any]) -> None:
    """Guard clause: refuse to proceed unless strictly in paper mode.

    Args:
        settings: Loaded settings.yaml dict.

    Raises:
        LiveTradingDisabledError: If settings.yaml mode.trading_mode is
            not "paper", or if is_live_trading_enabled(settings)
            returns True.
    """
    trading_mode = settings.get("mode", {}).get("trading_mode")
    if trading_mode != "paper":
        raise LiveTradingDisabledError(
            f"Refusing to start: mode.trading_mode is '{trading_mode}', "
            f"but this build only supports 'paper'. Live trading is not "
            f"implemented in this codebase."
        )

    if is_live_trading_enabled(settings):
        raise LiveTradingDisabledError(
            "Refusing to start: live trading flags are enabled "
            "(mode.enable_live_trading and/or ENABLE_LIVE_TRADING env "
            "var), but no live broker exists in this codebase. This is "
            "a paper/simulation-only build."
        )


def build_watchlist(settings: dict[str, Any], watchlist_cfg: dict[str, Any]) -> Watchlist:
    """Construct a Watchlist instance from loaded config.

    Args:
        settings: Loaded settings.yaml dict.
        watchlist_cfg: Loaded watchlist.yaml dict.

    Returns:
        A configured Watchlist instance (not yet refreshed).
    """
    filters = settings["universe_filters"]
    return Watchlist(
        candidates=list(watchlist_cfg["symbols"]),
        confirmation_symbol=watchlist_cfg["confirmation_symbol"],
        min_price=filters["min_price"],
        min_market_cap=filters["min_market_cap"],
    )


def build_risk_manager(settings: dict[str, Any], starting_equity: float) -> RiskManager:
    """Construct a RiskManager from loaded config.

    Args:
        settings: Loaded settings.yaml dict.
        starting_equity: Starting account equity for the session.

    Returns:
        A configured RiskManager instance.
    """
    risk_cfg = dict(settings["risk_controls"])
    risk_cfg["no_new_trades_after"] = settings["session"]["no_new_trades_after"]
    risk_cfg["force_flat_time"] = settings["session"]["force_flat_time"]
    risk_cfg["timezone"] = settings["session"]["timezone"]
    return RiskManager(risk_cfg, starting_equity=starting_equity)


def build_paper_broker(settings: dict[str, Any]) -> PaperBroker:
    """Construct the (only) broker implementation: PaperBroker.

    Args:
        settings: Loaded settings.yaml dict.

    Returns:
        A configured PaperBroker instance.
    """
    broker_cfg = settings["broker"]
    log_cfg = settings["logging"]
    return PaperBroker(
        starting_equity=broker_cfg["starting_paper_equity"],
        commission_per_share=broker_cfg.get("commission_per_share", 0.0),
        slippage_bps=broker_cfg.get("slippage_bps", 0.0),
        order_log_path=log_cfg.get("order_log_file", "logs/orders.log"),
    )


def run_session(
    settings: dict[str, Any],
    watchlist_cfg: dict[str, Any],
    bars_by_symbol: dict[str, pd.DataFrame],
    qqq_bars: pd.DataFrame,
    price_lookup: dict[str, float],
    market_cap_lookup: dict[str, float],
) -> dict[str, Any]:
    """Run one simulated trading session against supplied historical bars.

    This function performs the full pipeline for each symbol's bars in
    chronological order: compute market levels and candle features,
    check QQQ confirmation, scan for a liquidity-sweep signal, size the
    position, check risk controls, submit a simulated bracket order,
    manage any open position bar-by-bar, and force-flatten at the
    session's force_flat_time. All fills are simulated by PaperBroker;
    no network calls or credentials are involved anywhere in this path.

    Args:
        settings: Loaded settings.yaml dict.
        watchlist_cfg: Loaded watchlist.yaml dict.
        bars_by_symbol: Mapping of symbol -> OHLCV DataFrame (must
            include premarket + regular session bars, tz-aware
            timestamps).
        qqq_bars: OHLCV DataFrame for the QQQ confirmation symbol,
            aligned in time to `bars_by_symbol`.
        price_lookup: Mapping of symbol -> current price, for watchlist
            filtering.
        market_cap_lookup: Mapping of symbol -> market cap, for
            watchlist filtering.

    Returns:
        A summary dict: {"tradable_symbols": [...], "trades": [trade
        record dicts], "ending_equity": float}.

    Raises:
        LiveTradingDisabledError: If the safety gate fails (delegated
            to enforce_paper_mode).
    """
    enforce_paper_mode(settings)

    watchlist = build_watchlist(settings, watchlist_cfg)
    tradable = watchlist.refresh(price_lookup, market_cap_lookup)

    broker = build_paper_broker(settings)
    risk_manager = build_risk_manager(settings, starting_equity=broker.equity)
    journal = TradeJournal(settings["logging"].get("trade_journal_file", "logs/trade_journal.csv"))
    levels_engine = MarketLevels(timezone=settings["session"]["timezone"])

    strategy_cfg = settings["strategy"]["liquidity_sweep"]
    sizing_cfg = settings["position_sizing"]
    vol_lookback = settings["candle_features"]["volume_lookback_bars"]
    vol_multiplier = settings["candle_features"]["volume_spike_multiplier"]
    neutral_band = strategy_cfg["qqq_confirmation"]["neutral_band_pct"]

    trade_records: list[dict[str, Any]] = []
    open_positions: dict[str, Position] = {}

    for symbol in tradable:
        bars = bars_by_symbol.get(symbol)
        if bars is None or bars.empty:
            continue

        levels = levels_engine.compute_all(bars)
        avg_volume_series = rolling_average_volume(bars["volume"], lookback=vol_lookback)

        for idx in range(len(bars)):
            bar_row = bars.iloc[idx]
            bar = {
                "symbol": symbol,
                "timestamp": bar_row["timestamp"],
                "open": bar_row["open"],
                "high": bar_row["high"],
                "low": bar_row["low"],
                "close": bar_row["close"],
                "volume": bar_row["volume"],
            }
            now = bar["timestamp"]

            position = open_positions.get(symbol)
            if position is not None:
                if risk_manager.should_force_flat(now):
                    record = broker.force_close(position, bar)
                    journal.record_trade(record)
                    risk_manager.register_trade_result(record["pnl"])
                    trade_records.append(record)
                    del open_positions[symbol]
                    continue

                record = broker.process_bar(position, bar)
                if record is not None:
                    journal.record_trade(record)
                    risk_manager.register_trade_result(record["pnl"])
                    trade_records.append(record)
                    del open_positions[symbol]
                continue

            allowed, _reason = risk_manager.can_open_new_trade(now)
            if not allowed:
                continue

            avg_volume = avg_volume_series.iloc[idx]
            if pd.isna(avg_volume) or not volume_spike(
                bar["volume"], avg_volume, vol_multiplier
            ):
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

    return {
        "tradable_symbols": tradable,
        "trades": trade_records,
        "ending_equity": broker.equity,
    }


def main() -> None:
    """CLI entry point.

    Loads configuration, enforces the paper-mode safety gate, and (in
    the absence of a configured historical/paper data source in v1)
    reports readiness rather than attempting any live network access.
    """
    settings = load_settings()
    watchlist_cfg = load_watchlist()

    try:
        enforce_paper_mode(settings)
    except LiveTradingDisabledError as exc:
        print(f"[REFUSED TO START] {exc}", file=sys.stderr)
        sys.exit(1)

    print("Liquidity Sweep Bot — paper/simulation mode confirmed.")
    print(f"Trading mode: {settings['mode']['trading_mode']}")
    print(f"Session window: {settings['session']['session_start']} - "
          f"{settings['session']['session_end']} "
          f"{settings['session']['timezone']}")
    print(f"Watchlist candidates: {watchlist_cfg['symbols']}")
    print(
        "No historical/live market data source is configured in this "
        "v1 build. To run a simulated session, call run_session() "
        "directly with your own OHLCV bars (see docstring)."
    )


if __name__ == "__main__":
    main()
