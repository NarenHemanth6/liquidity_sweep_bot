"""
data/examples/generate_example_data.py

(Re)generates the synthetic example CSV files under data/examples/:
    data/examples/DEMO_bars.csv
    data/examples/QQQ_bars.csv

These are fully synthetic (fake, not real market data), reusing the
same deterministic generator as sample_data/backtest/, so that
scripts/run_real_csv_backtest.py has a small, realistic dataset to
demonstrate the "place your own CSVs" workflow against without
requiring any real market data. See
sample_data/backtest/generate_backtest_data.py for the generation
details (1 winning trade, 1 losing trade, and 1 day with no valid
setup, across 3 trading days).

Usage:
    python data/examples/generate_example_data.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sample_data.backtest.generate_backtest_data import generate_backtest_bars  # noqa: E402


def main() -> None:
    """Generate the example bars and write them to CSV files in this folder."""
    stock_bars, qqq_bars = generate_backtest_bars()

    out_dir = Path(__file__).parent
    stock_path = out_dir / "DEMO_bars.csv"
    qqq_path = out_dir / "QQQ_bars.csv"

    stock_bars.to_csv(stock_path, index=False)
    qqq_bars.to_csv(qqq_path, index=False)

    print(f"Wrote {len(stock_bars)} DEMO bars to {stock_path}")
    print(f"Wrote {len(qqq_bars)} QQQ bars to {qqq_path}")


if __name__ == "__main__":
    main()
