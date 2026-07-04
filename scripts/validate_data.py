"""
scripts/validate_data.py

Validates every historical OHLCV CSV file in a local data directory
(default: data/raw/) and prints a clean report. Local file checks
only -- no network access, no broker connection, no credentials of any
kind are involved anywhere in this path.

Usage:
    python -m scripts.validate_data
    python -m scripts.validate_data --data-dir data/examples --confirmation-symbol QQQ
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backtesting.data_validation import validate_directory  # noqa: E402

DEFAULT_DATA_DIR = "data/raw"
DEFAULT_CONFIRMATION_SYMBOL = "QQQ"


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the validation run."""
    parser = argparse.ArgumentParser(description="Validate local historical OHLCV CSV files.")
    parser.add_argument(
        "--data-dir",
        default=DEFAULT_DATA_DIR,
        help=f"Directory of '{{symbol}}_bars.csv' files to validate (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--confirmation-symbol",
        default=DEFAULT_CONFIRMATION_SYMBOL,
        help=f"Directional confirmation symbol required (default: {DEFAULT_CONFIRMATION_SYMBOL})",
    )
    return parser.parse_args()


def main() -> None:
    """Validate every CSV file in the target directory and print a report."""
    args = _parse_args()
    data_dir = PROJECT_ROOT / args.data_dir

    result = validate_directory(data_dir, confirmation_symbol=args.confirmation_symbol)

    print("=" * 70)
    print(f"DATA VALIDATION REPORT -- {data_dir}")
    print("=" * 70)

    if not result.files:
        print("No CSV files found.")
        sys.exit(1)

    for f in result.files:
        status = "OK" if f.is_valid else "FAILED"
        print(f"\n{Path(f.path).name:<30} [{status}]  rows={f.row_count}  symbols={f.symbols}")
        for err in f.errors:
            print(f"  ERROR:   {err}")
        for warn in f.warnings:
            print(f"  WARNING: {warn}")

    print("\n" + "-" * 70)
    if result.is_valid:
        print(f"All files passed validation. {args.confirmation_symbol} confirmation data found.")
    else:
        print("VALIDATION FAILED. Fix the errors above before backtesting.")
    print("=" * 70)

    sys.exit(0 if result.is_valid else 1)


if __name__ == "__main__":
    main()
