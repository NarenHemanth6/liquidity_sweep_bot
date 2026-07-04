"""
scripts/run_backtest.py

Runs a historical backtest of the liquidity sweep strategy against
local CSV files only, and prints a clean summary report. This script
never places or attempts a real order: it only ever exercises
PaperBroker via src.backtesting.engine.run_backtest(), which is
paper/simulation only. No network access, no broker connection, and no
credentials are used anywhere in this path.

Usage:
    python -m scripts.run_backtest
    python -m scripts.run_backtest --data-dir sample_data/backtest --symbol DEMO
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backtesting.data_loader import load_backtest_dataset  # noqa: E402
from src.backtesting.engine import LiveTradingDisabledError, run_backtest  # noqa: E402
from src.config_loader import load_settings  # noqa: E402
from src.journal.trade_journal import TradeJournal  # noqa: E402

DEFAULT_DATA_DIR = "sample_data/backtest"
DEFAULT_SYMBOL = "DEMO"
DEFAULT_CONFIRMATION_SYMBOL = "QQQ"
BACKTEST_JOURNAL_PATH = "logs/backtest_trade_journal.csv"
BACKTEST_ORDER_LOG_PATH = "logs/backtest_orders.log"


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the backtest run.

    Returns:
        Parsed arguments: data_dir, symbols (list[str]), confirmation_symbol.
    """
    parser = argparse.ArgumentParser(description="Run a local CSV-only historical backtest.")
    parser.add_argument(
        "--data-dir",
        default=DEFAULT_DATA_DIR,
        help=f"Directory containing '{{symbol}}_bars.csv' files (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--symbol",
        action="append",
        dest="symbols",
        help="Tradable symbol to include (repeatable). Defaults to DEMO.",
    )
    parser.add_argument(
        "--confirmation-symbol",
        default=DEFAULT_CONFIRMATION_SYMBOL,
        help=f"Directional confirmation symbol (default: {DEFAULT_CONFIRMATION_SYMBOL})",
    )
    args = parser.parse_args()
    if not args.symbols:
        args.symbols = [DEFAULT_SYMBOL]
    return args


def _print_trade_row(trade: dict[str, Any], index: int) -> None:
    """Print one closed trade's detail line.

    Args:
        trade: A trade record dict (see journal/trade_journal.py
            REQUIRED_COLUMNS).
        index: 1-based sequence number of this trade, for display.
    """
    outcome = "WIN " if trade["pnl"] > 0 else "LOSS"
    print(
        f"  #{index:<2} {trade['timestamp']}  {trade['symbol']:<6} "
        f"{trade['direction']:<5} qty={trade['quantity']:<6} "
        f"entry={trade['entry']:.2f} exit={trade['exit']:.2f} "
        f"pnl=${trade['pnl']:>10.2f}  [{outcome}]  exit_reason={trade['reason_exit']}"
    )


def _print_report(result, symbols: list[str]) -> None:
    """Print the full backtest summary report to stdout.

    Args:
        result: A BacktestResult from src.backtesting.engine.run_backtest.
        symbols: The tradable symbols requested for this run.
    """
    metrics = result.metrics

    print("=" * 70)
    print("LIQUIDITY SWEEP BOT -- HISTORICAL BACKTEST (paper/simulation only)")
    print("=" * 70)
    print(f"Symbols requested:      {symbols}")
    print(f"Tradable symbols today: {result.tradable_symbols}")
    print(f"Trading days simulated: {len(result.daily_results)}")

    print("\nPer-day summary:")
    for day in result.daily_results:
        print(f"  {day['date']}  trades={day['trades']:<3} ending_equity=${day['ending_equity']:.2f}")

    if result.trades:
        print("\nTrade-by-trade detail:")
        for i, trade in enumerate(result.trades, start=1):
            _print_trade_row(trade, i)

    print("\n" + "-" * 70)
    print("PERFORMANCE SUMMARY")
    print("-" * 70)
    print(f"Total trades:       {metrics['total_trades']}")
    print(f"Wins:               {metrics['wins']}")
    print(f"Losses:             {metrics['losses']}")
    print(f"Win rate:           {metrics['win_rate'] * 100:.1f}%")
    print(f"Gross profit:       ${metrics['gross_profit']:.2f}")
    print(f"Gross loss:         ${metrics['gross_loss']:.2f}")
    print(f"Net P&L:            ${metrics['net_pnl']:.2f}")
    print(f"Average win:        ${metrics['average_win']:.2f}")
    print(f"Average loss:       ${metrics['average_loss']:.2f}")
    profit_factor = metrics["profit_factor"]
    pf_display = "inf" if profit_factor == float("inf") else f"{profit_factor:.2f}"
    print(f"Profit factor:      {pf_display}")
    print(f"Max drawdown:       ${metrics['max_drawdown']:.2f}")
    print(f"Ending equity:      ${metrics['ending_equity']:.2f}")
    print("=" * 70)
    print(f"Per-trade journal CSV written to: {BACKTEST_JOURNAL_PATH}")
    print("=" * 70)


def main() -> None:
    """Load local CSV historical data, run the backtest, print the report."""
    args = _parse_args()

    settings = load_settings(str(PROJECT_ROOT / "config" / "settings.yaml"))
    settings = dict(settings)
    settings["logging"] = dict(settings["logging"])
    settings["logging"]["trade_journal_file"] = BACKTEST_JOURNAL_PATH
    settings["logging"]["order_log_file"] = BACKTEST_ORDER_LOG_PATH

    watchlist_cfg = {"symbols": args.symbols, "confirmation_symbol": args.confirmation_symbol}

    bars_by_symbol, qqq_bars = load_backtest_dataset(
        data_dir=PROJECT_ROOT / args.data_dir,
        symbols=args.symbols,
        confirmation_symbol=args.confirmation_symbol,
    )

    # Synthetic price/market-cap lookup so the requested symbols clear
    # the universe filters (price > $100, market cap > $1B). Entirely
    # fabricated values used only to satisfy the watchlist filter.
    price_lookup = {symbol: 150.50 for symbol in args.symbols}
    market_cap_lookup = {symbol: 50_000_000_000.0 for symbol in args.symbols}

    try:
        result = run_backtest(
            settings=settings,
            watchlist_cfg=watchlist_cfg,
            bars_by_symbol=bars_by_symbol,
            qqq_bars=qqq_bars,
            price_lookup=price_lookup,
            market_cap_lookup=market_cap_lookup,
        )
    except LiveTradingDisabledError as exc:  # pragma: no cover - safety guard
        print(f"[REFUSED TO START] {exc}", file=sys.stderr)
        sys.exit(1)

    _print_report(result, args.symbols)

    journal = TradeJournal(BACKTEST_JOURNAL_PATH)
    journal_df = journal.read_all()
    print(f"\nJournal file now contains {len(journal_df)} row(s).")


if __name__ == "__main__":
    main()
