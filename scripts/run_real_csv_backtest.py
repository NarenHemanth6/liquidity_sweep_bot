"""
scripts/run_real_csv_backtest.py

Runs the liquidity sweep strategy against locally-placed historical
CSV files (default directory: data/raw/) and prints an extended
summary report. This script never places or attempts a real order: it
only ever exercises PaperBroker via src.backtesting.engine.run_backtest,
which is paper/simulation only. No network access, no broker
connection, and no credentials are used anywhere in this path.

Before backtesting, this script validates every CSV file in the data
directory (see src.backtesting.data_validation) and refuses to run if
validation fails or no confirmation-symbol (default "QQQ") file is
present.

Usage:
    python -m scripts.run_real_csv_backtest
    python -m scripts.run_real_csv_backtest --data-dir data/examples
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backtesting.data_loader import SYMBOL_FILE_SUFFIXES, load_backtest_dataset  # noqa: E402
from src.backtesting.data_validation import validate_directory  # noqa: E402
from src.backtesting.engine import LiveTradingDisabledError, run_backtest  # noqa: E402
from src.config_loader import load_settings  # noqa: E402
from src.journal.trade_journal import TradeJournal  # noqa: E402

DEFAULT_DATA_DIR = "data/raw"
DEFAULT_CONFIRMATION_SYMBOL = "QQQ"
REAL_CSV_JOURNAL_PATH = "logs/real_csv_backtest_journal.csv"
REAL_CSV_ORDER_LOG_PATH = "logs/real_csv_backtest_orders.log"


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the real-CSV backtest run."""
    parser = argparse.ArgumentParser(
        description="Run a backtest against locally-placed historical CSV files."
    )
    parser.add_argument(
        "--data-dir",
        default=DEFAULT_DATA_DIR,
        help=f"Directory of '{{symbol}}_bars.csv' or '{{symbol}}_1min.csv' files (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--confirmation-symbol",
        default=DEFAULT_CONFIRMATION_SYMBOL,
        help=f"Directional confirmation symbol (default: {DEFAULT_CONFIRMATION_SYMBOL})",
    )
    parser.add_argument(
        "--append-journal",
        action="store_true",
        help=(
            "Append this run's trades to any existing journal file instead of the "
            "default (overwrite it, so the journal contains only this run's trades)."
        ),
    )
    return parser.parse_args()


def _discover_tradable_symbols(data_dir: Path, confirmation_symbol: str) -> list[str]:
    """Discover tradable symbols from historical CSV files in data_dir.

    Recognizes every naming convention in SYMBOL_FILE_SUFFIXES (e.g.
    "{symbol}_bars.csv" and "{symbol}_1min.csv", the latter matching
    scripts/download_ibkr_bars.py's output directly, with no rename
    step required).

    Args:
        data_dir: Directory to scan.
        confirmation_symbol: Excluded from the discovered list (it's
            loaded separately, for directional confirmation only).

    Returns:
        Sorted list of tradable symbols found.
    """
    if not data_dir.exists():
        return []
    symbols: set[str] = set()
    for suffix in SYMBOL_FILE_SUFFIXES:
        for path in data_dir.glob(f"*{suffix}.csv"):
            stem = path.stem
            symbol = stem[: -len(suffix)] if stem.endswith(suffix) else stem
            if symbol and symbol != confirmation_symbol:
                symbols.add(symbol)
    return sorted(symbols)


def _best_and_worst_trade(
    trades: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return the (best, worst) trade by P&L, or (None, None) if empty."""
    if not trades:
        return None, None
    return max(trades, key=lambda t: t["pnl"]), min(trades, key=lambda t: t["pnl"])


def _trades_per_symbol(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate trade count and total P&L per symbol."""
    per_symbol: dict[str, dict[str, Any]] = {}
    for t in trades:
        entry = per_symbol.setdefault(t["symbol"], {"trades": 0, "pnl": 0.0})
        entry["trades"] += 1
        entry["pnl"] += t["pnl"]
    return per_symbol


def _daily_pnl(trades: list[dict[str, Any]]) -> dict[str, float]:
    """Aggregate total P&L per calendar day (by trade exit timestamp)."""
    per_day: dict[str, float] = {}
    for t in trades:
        day = str(pd.Timestamp(t["timestamp"]).date())
        per_day[day] = per_day.get(day, 0.0) + t["pnl"]
    return dict(sorted(per_day.items()))


def _print_trade_row(trade: dict[str, Any], index: int) -> None:
    """Print one closed trade's detail line."""
    outcome = "WIN " if trade["pnl"] > 0 else "LOSS"
    print(
        f"  #{index:<2} {trade['timestamp']}  {trade['symbol']:<6} "
        f"{trade['direction']:<5} qty={trade['quantity']:<6} "
        f"entry={trade['entry']:.2f} exit={trade['exit']:.2f} "
        f"pnl=${trade['pnl']:>10.2f}  [{outcome}]  exit_reason={trade['reason_exit']}"
    )


def _print_report(result, symbols: list[str]) -> None:
    """Print the full extended real-CSV backtest report to stdout."""
    metrics = result.metrics
    best, worst = _best_and_worst_trade(result.trades)
    per_symbol = _trades_per_symbol(result.trades)
    per_day = _daily_pnl(result.trades)

    print("=" * 70)
    print("LIQUIDITY SWEEP BOT -- REAL CSV HISTORICAL BACKTEST (paper/simulation only)")
    print("=" * 70)
    print(f"Symbols discovered:     {symbols}")
    print(f"Tradable symbols today: {result.tradable_symbols}")
    print(f"Trading days simulated: {len(result.daily_results)}")

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
    print(f"Net P&L:            ${metrics['net_pnl']:.2f}")
    profit_factor = metrics["profit_factor"]
    pf_display = "inf" if profit_factor == float("inf") else f"{profit_factor:.2f}"
    print(f"Profit factor:      {pf_display}")
    print(f"Max drawdown:       ${metrics['max_drawdown']:.2f}")
    print(f"Ending equity:      ${metrics['ending_equity']:.2f}")

    print("\nBest trade:")
    if best is not None:
        print(f"  {best['symbol']} {best['direction']} pnl=${best['pnl']:.2f} ({best['timestamp']})")
    else:
        print("  (no trades)")

    print("Worst trade:")
    if worst is not None:
        print(f"  {worst['symbol']} {worst['direction']} pnl=${worst['pnl']:.2f} ({worst['timestamp']})")
    else:
        print("  (no trades)")

    print("\nTrades per symbol:")
    if per_symbol:
        for symbol, stats in per_symbol.items():
            print(f"  {symbol:<6} trades={stats['trades']:<3} pnl=${stats['pnl']:.2f}")
    else:
        print("  (no trades)")

    print("\nDaily P&L:")
    if per_day:
        for day, pnl in per_day.items():
            print(f"  {day}  pnl=${pnl:.2f}")
    else:
        print("  (no trades)")

    print("\n" + "=" * 70)
    print(f"Per-trade journal CSV written to: {REAL_CSV_JOURNAL_PATH}")
    print("=" * 70)


def main() -> None:
    """Validate, load, and backtest local CSV files; print the report."""
    args = _parse_args()
    data_dir = PROJECT_ROOT / args.data_dir

    validation = validate_directory(data_dir, confirmation_symbol=args.confirmation_symbol)
    if not validation.is_valid:
        print(f"[VALIDATION FAILED] {data_dir} did not pass validation.", file=sys.stderr)
        print("Run `python -m scripts.validate_data` for the full report.", file=sys.stderr)
        for f in validation.files:
            for err in f.errors:
                print(f"  {Path(f.path).name}: {err}", file=sys.stderr)
        sys.exit(1)

    symbols = _discover_tradable_symbols(data_dir, args.confirmation_symbol)
    if not symbols:
        print(
            f"[NO DATA] No tradable '{{symbol}}_bars.csv' or '{{symbol}}_1min.csv' files found in "
            f"{data_dir} (besides the confirmation symbol).",
            file=sys.stderr,
        )
        sys.exit(1)

    settings = load_settings(str(PROJECT_ROOT / "config" / "settings.yaml"))
    settings = dict(settings)
    settings["logging"] = dict(settings["logging"])
    settings["logging"]["trade_journal_file"] = REAL_CSV_JOURNAL_PATH
    settings["logging"]["order_log_file"] = REAL_CSV_ORDER_LOG_PATH
    settings["universe_filters"] = dict(settings["universe_filters"])
    settings["universe_filters"]["min_market_cap"] = 0.0  # minute bars carry no market-cap data

    watchlist_cfg = {"symbols": symbols, "confirmation_symbol": args.confirmation_symbol}

    bars_by_symbol, qqq_bars = load_backtest_dataset(
        data_dir=data_dir, symbols=symbols, confirmation_symbol=args.confirmation_symbol
    )

    # Price filter is derived from the data itself (each symbol's most
    # recent close) since real minute-bar files carry no live quote or
    # market-cap feed.
    price_lookup = {
        symbol: float(bars.iloc[-1]["close"]) for symbol, bars in bars_by_symbol.items() if not bars.empty
    }
    market_cap_lookup = {symbol: 1.0 for symbol in symbols}

    try:
        result = run_backtest(
            settings=settings,
            watchlist_cfg=watchlist_cfg,
            bars_by_symbol=bars_by_symbol,
            qqq_bars=qqq_bars,
            price_lookup=price_lookup,
            market_cap_lookup=market_cap_lookup,
            overwrite_journal=not args.append_journal,
        )
    except LiveTradingDisabledError as exc:  # pragma: no cover - safety guard
        print(f"[REFUSED TO START] {exc}", file=sys.stderr)
        sys.exit(1)

    _print_report(result, symbols)

    journal = TradeJournal(REAL_CSV_JOURNAL_PATH)
    journal_df = journal.read_all()
    print(f"\nJournal file now contains {len(journal_df)} row(s).")


if __name__ == "__main__":
    main()
