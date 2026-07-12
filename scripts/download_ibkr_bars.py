"""
scripts/download_ibkr_bars.py

Downloads CLOSED historical 1-minute OHLCV bars from Interactive
Brokers' TWS / IB Gateway API (the `ibapi` package) and writes them to
local CSV files, ready for scripts/validate_data.py and
scripts/run_real_csv_backtest.py.

Historical data only:
    - The only IBKR API call this script makes is `reqHistoricalData`.
    - It never calls `placeOrder`, `cancelOrder`, or any other
      order-routing method.
    - It never requests account, portfolio, or position data
      (`reqAccountUpdates`, `reqPositions`, etc.).
    - It never reads or stores a broker account number, username, or
      password. `IBKR_HOST` / `IBKR_PORT` / `IBKR_CLIENT_ID` are local
      TWS/IB Gateway connection settings, not credentials.
    - No live trading, no Trade The Pool, no Alpaca, no Webull.

See docs/ibkr_historical_data_setup.md for TWS/IB Gateway setup
instructions (paper-trading API port strongly recommended).

Usage:
    python -m scripts.download_ibkr_bars --symbols QQQ NVDA TSLA AAPL \\
        --start 2026-07-01 --end 2026-07-01 --bar-size "1 min" \\
        --output-dir data/raw --host 127.0.0.1 --port 7497 --client-id 101
"""

from __future__ import annotations

import argparse
import sys
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import get_env  # noqa: E402

try:
    from ibapi.client import EClient
    from ibapi.common import BarData
    from ibapi.contract import Contract
    from ibapi.wrapper import EWrapper
except ImportError as exc:  # pragma: no cover - ibapi is a listed dependency
    raise ImportError(
        "The 'ibapi' package is required for scripts/download_ibkr_bars.py. "
        "Install it with: pip install -r requirements.txt"
    ) from exc

REQUIRED_COLUMNS = ("timestamp", "symbol", "open", "high", "low", "close", "volume")
DEFAULT_TIMEZONE = "America/New_York"

DEFAULT_HOST = get_env("IBKR_HOST", "127.0.0.1")
DEFAULT_PORT = int(get_env("IBKR_PORT", "7497") or "7497")
DEFAULT_CLIENT_ID = int(get_env("IBKR_CLIENT_ID", "101") or "101")
DEFAULT_BAR_SIZE = "1 min"
DEFAULT_OUTPUT_DIR = "data/raw"

CONNECT_TIMEOUT_SECONDS = 10.0
REQUEST_TIMEOUT_SECONDS = 60.0


class HistoricalDataRequestError(RuntimeError):
    """Raised when IBKR reports an error for a historical data request."""


class IBKRHistoricalDataApp(EWrapper, EClient):
    """Minimal EWrapper/EClient pair used ONLY to request historical bars.

    This class deliberately implements nothing beyond the historical-
    data request/response cycle and the connection handshake -- no
    order-related method (placeOrder, cancelOrder, reqAccountUpdates,
    reqPositions, etc.) is overridden or called anywhere in this class.
    """

    def __init__(self) -> None:
        EClient.__init__(self, self)
        self._next_req_id = 0
        self._bars: dict[int, list[BarData]] = {}
        self._done: dict[int, threading.Event] = {}
        self._errors: dict[int, str] = {}
        self._connected_event = threading.Event()

    def next_request_id(self) -> int:
        """Return a fresh, unique request id for this session."""
        req_id = self._next_req_id
        self._next_req_id += 1
        return req_id

    def wait_until_connected(self, timeout: float) -> bool:
        """Block until the initial connection handshake completes."""
        return self._connected_event.wait(timeout=timeout)

    # -- EWrapper callbacks --

    def nextValidId(self, orderId: int) -> None:
        """IBKR sends this once the connection handshake is complete."""
        self._connected_event.set()

    def historicalData(self, reqId: int, bar: BarData) -> None:
        self._bars.setdefault(reqId, []).append(bar)

    def historicalDataEnd(self, reqId: int, start: str, end: str) -> None:
        self._done.setdefault(reqId, threading.Event()).set()

    def error(self, reqId: int, errorCode: int, errorString: str, *args: Any) -> None:
        # reqId is -1 for connection-level notices unrelated to any
        # single request; only per-request errors need to unblock a
        # waiting request_historical_bars() call.
        if reqId is not None and reqId >= 0:
            self._errors[reqId] = f"[{errorCode}] {errorString}"
            self._done.setdefault(reqId, threading.Event()).set()

    # -- Historical data request --

    def request_historical_bars(
        self, symbol: str, end_date_time: str, duration: str, bar_size: str
    ) -> list[BarData]:
        """Request and block for one symbol's closed historical bars.

        Raises:
            TimeoutError: If no response arrives within
                REQUEST_TIMEOUT_SECONDS.
            HistoricalDataRequestError: If IBKR reports an error for
                this specific request.
        """
        req_id = self.next_request_id()
        self._done[req_id] = threading.Event()

        contract = Contract()
        contract.symbol = symbol
        contract.secType = "STK"
        contract.exchange = "SMART"
        contract.currency = "USD"

        self.reqHistoricalData(
            req_id,
            contract,
            end_date_time,
            duration,
            bar_size,
            "TRADES",
            0,  # useRTH=0: include premarket bars, matching this project's PMH/PML needs
            2,  # formatDate=2: bar.date is epoch seconds (UTC), unambiguous to parse
            False,
            [],
        )

        if not self._done[req_id].wait(timeout=REQUEST_TIMEOUT_SECONDS):
            raise TimeoutError(f"Timed out waiting for historical data for {symbol}")

        if req_id in self._errors:
            raise HistoricalDataRequestError(
                f"IBKR returned an error for {symbol}: {self._errors[req_id]}"
            )

        return self._bars.get(req_id, [])


def _duration_str(start: date, end: date) -> str:
    """Convert a start/end date range into IBKR's `durationStr` format."""
    days = (end - start).days + 1
    if days < 1:
        raise ValueError("--end must not be before --start")
    return f"{days} D"


def _end_date_time_str(end: date) -> str:
    """Convert the end date into IBKR's `endDateTime` format (end of day)."""
    return f"{end:%Y%m%d}-23:59:59"


def bars_to_dataframe(symbol: str, bars: list[BarData], timezone: str = DEFAULT_TIMEZONE) -> pd.DataFrame:
    """Convert IBKR BarData objects into this project's CSV schema.

    Args:
        symbol: Ticker symbol these bars belong to.
        bars: BarData objects as returned by request_historical_bars()
            (formatDate=2, so bar.date is an epoch-seconds string).
        timezone: IANA timezone the output `timestamp` column is
            expressed in (naive, matching src/backtesting/data_loader.py).

    Returns:
        A DataFrame with REQUIRED_COLUMNS, one row per bar.
    """
    rows = []
    for bar in bars:
        ts = pd.Timestamp(int(bar.date), unit="s", tz="UTC").tz_convert(timezone).tz_localize(None)
        rows.append(
            {
                "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": symbol,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }
        )
    return pd.DataFrame(rows, columns=list(REQUIRED_COLUMNS))


def write_symbol_csv(df: pd.DataFrame, output_dir: str | Path, symbol: str) -> Path:
    """Write one symbol's bars to '{output_dir}/{symbol}_1min.csv'."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{symbol}_1min.csv"
    df.to_csv(path, index=False)
    return path


def download_all(
    symbols: list[str],
    start: date,
    end: date,
    bar_size: str,
    output_dir: str | Path,
    host: str,
    port: int,
    client_id: int,
) -> list[Path]:
    """Connect to TWS/IB Gateway, download each symbol's bars, write CSVs.

    Always disconnects, even if a request fails partway through.

    Raises:
        ConnectionError: If the connection handshake never completes.
        TimeoutError / HistoricalDataRequestError: Propagated from a
            failed per-symbol request.
    """
    end_date_time = _end_date_time_str(end)
    duration = _duration_str(start, end)

    app = IBKRHistoricalDataApp()
    app.connect(host, port, client_id)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()

    try:
        if not app.wait_until_connected(timeout=CONNECT_TIMEOUT_SECONDS):
            raise ConnectionError(
                f"Could not connect to IBKR TWS/IB Gateway at {host}:{port} within "
                f"{CONNECT_TIMEOUT_SECONDS:.0f}s. Is TWS/IB Gateway running with the "
                f"API enabled? See docs/ibkr_historical_data_setup.md."
            )

        output_paths = []
        for symbol in symbols:
            bars = app.request_historical_bars(symbol, end_date_time, duration, bar_size)
            df = bars_to_dataframe(symbol, bars)
            output_paths.append(write_symbol_csv(df, output_dir, symbol))
        return output_paths
    finally:
        app.disconnect()
        thread.join(timeout=5)


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the IBKR historical download run."""
    parser = argparse.ArgumentParser(
        description="Download closed historical 1-minute OHLCV bars from IBKR TWS/IB Gateway."
    )
    parser.add_argument("--symbols", nargs="+", required=True, help="Ticker symbols to download.")
    parser.add_argument("--start", required=True, help="Start date, YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="End date, YYYY-MM-DD (inclusive).")
    parser.add_argument("--bar-size", default=DEFAULT_BAR_SIZE, help=f"IBKR bar size (default: {DEFAULT_BAR_SIZE!r}).")
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to write '{{symbol}}_1min.csv' files into (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="TWS/IB Gateway host (default: IBKR_HOST env var).")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="TWS/IB Gateway API port (default: IBKR_PORT env var)."
    )
    parser.add_argument(
        "--client-id", type=int, default=DEFAULT_CLIENT_ID, help="API client id (default: IBKR_CLIENT_ID env var)."
    )
    return parser.parse_args()


def main() -> None:
    """Validate args, download every symbol's bars, and report the result."""
    args = _parse_args()

    try:
        start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
        end_date = datetime.strptime(args.end, "%Y-%m-%d").date()
    except ValueError as exc:
        print(f"[INVALID ARGS] --start/--end must be YYYY-MM-DD: {exc}", file=sys.stderr)
        sys.exit(1)

    if end_date < start_date:
        print("[INVALID ARGS] --end must not be before --start", file=sys.stderr)
        sys.exit(1)

    print("=" * 70)
    print("IBKR HISTORICAL DATA DOWNLOAD (historical bars only -- no orders, no live trading)")
    print("=" * 70)
    print(f"Symbols:     {args.symbols}")
    print(f"Date range:  {args.start} to {args.end}")
    print(f"Bar size:    {args.bar_size}")
    print(f"Output dir:  {args.output_dir}")
    print(f"TWS/Gateway: {args.host}:{args.port} (clientId={args.client_id})")
    print()

    try:
        paths = download_all(
            symbols=args.symbols,
            start=start_date,
            end=end_date,
            bar_size=args.bar_size,
            output_dir=args.output_dir,
            host=args.host,
            port=args.port,
            client_id=args.client_id,
        )
    except (ConnectionError, TimeoutError, HistoricalDataRequestError) as exc:
        print(f"[DOWNLOAD FAILED] {exc}", file=sys.stderr)
        sys.exit(1)

    for path in paths:
        print(f"  wrote {path}")

    print("\nNext steps (no rename needed -- '_1min.csv' files are recognized directly):")
    print(f"  1. .venv\\Scripts\\python.exe -m scripts.validate_data --data-dir {args.output_dir}")
    print(f"  2. .venv\\Scripts\\python.exe -m scripts.run_real_csv_backtest --data-dir {args.output_dir}")
    print("=" * 70)


if __name__ == "__main__":
    main()
