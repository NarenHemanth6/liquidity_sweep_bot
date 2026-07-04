"""
scripts/run_sample_simulation.py

Runs the paper-trading engine (src.main.run_session) against the
synthetic sample data in sample_data/, and prints a human-readable
report for every simulated trade. This script never places or
attempts a real order: it only ever exercises PaperBroker via
run_session(), which is paper/simulation only.

Usage:
    python -m scripts.run_sample_simulation
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sample_data.generate_sample_data import SYMBOL, generate_sample_bars  # noqa: E402
from src.config_loader import load_settings  # noqa: E402
from src.journal.trade_journal import TradeJournal  # noqa: E402
from src.main import LiveTradingDisabledError, run_session  # noqa: E402

SAMPLE_JOURNAL_PATH = "logs/sample_trade_journal.csv"
SAMPLE_ORDER_LOG_PATH = "logs/sample_orders.log"


def _print_trade_report(trade: dict[str, Any], index: int) -> None:
    """Print one trade's full detail block in the required report format.

    Args:
        trade: A trade record dict as produced by PaperBroker /
            TradeJournal (see journal/trade_journal.py REQUIRED_COLUMNS).
        index: 1-based sequence number of this trade, for display.
    """
    print(f"\n--- Trade #{index} ---")
    print(f"Symbol:                {trade['symbol']}")
    print(f"Direction:             {trade['direction']}")
    print(f"Liquidity level swept: {trade['swept_level']:.2f}")
    print(f"Entry price:           {trade['entry']:.2f}")
    print(f"Stop price:            {trade['stop']:.2f}")
    print(f"Target price(s):       {trade['target']}")
    print(f"Quantity:              {trade['quantity']}")
    print(f"Risk amount:           ${trade['risk_amount']:.2f}")
    print(f"Simulated exit price:  {trade['exit']:.2f}")
    print(f"Simulated P&L:         ${trade['pnl']:.2f}")
    print(f"Entry reason:          {trade['reason_entry']}")
    print(f"Exit reason:           {trade['reason_exit']}")


def main() -> None:
    """Load sample data, run one paper-trading session, print + journal results."""
    settings = load_settings(str(PROJECT_ROOT / "config" / "settings.yaml"))
    settings["logging"] = dict(settings["logging"])
    settings["logging"]["trade_journal_file"] = SAMPLE_JOURNAL_PATH
    settings["logging"]["order_log_file"] = SAMPLE_ORDER_LOG_PATH

    watchlist_cfg = {
        "symbols": [SYMBOL],
        "confirmation_symbol": "QQQ",
    }

    stock_bars, qqq_bars = generate_sample_bars()
    bars_by_symbol = {SYMBOL: stock_bars}

    # Synthetic price/market-cap lookup so DEMO clears the universe
    # filters (price > $100, market cap > $1B). Entirely fabricated
    # values for this fictional demo symbol.
    price_lookup = {SYMBOL: 150.50}
    market_cap_lookup = {SYMBOL: 50_000_000_000.0}

    try:
        result = run_session(
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

    print("=" * 60)
    print("LIQUIDITY SWEEP BOT — SAMPLE PAPER SIMULATION (Day: 2026-07-01)")
    print("=" * 60)
    print(f"Tradable symbols today: {result['tradable_symbols']}")
    print(f"Trades detected/simulated: {len(result['trades'])}")

    for i, trade in enumerate(result["trades"], start=1):
        _print_trade_report(trade, i)

    print("\n" + "=" * 60)
    print(f"Ending simulated equity: ${result['ending_equity']:.2f}")
    print(f"Trade journal written to: {SAMPLE_JOURNAL_PATH}")
    print("=" * 60)

    journal = TradeJournal(SAMPLE_JOURNAL_PATH)
    journal_df = journal.read_all()
    print(f"\nJournal file now contains {len(journal_df)} row(s).")


if __name__ == "__main__":
    main()
