"""
Tests for scripts/download_ibkr_bars.py.

Every test in this file uses hand-built fake/mock objects standing in
for ibapi's EClient/EWrapper -- no test here ever opens a real socket,
starts a real TWS/IB Gateway session, or touches the network. The
safety-guard tests at the bottom assert this script contains no order-
placement, live-broker, or account-credential code of any kind.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from ibapi.common import BarData

import scripts.download_ibkr_bars as script
from src.backtesting.data_loader import load_backtest_dataset
from src.backtesting.data_validation import validate_directory

NY = ZoneInfo("America/New_York")


def _epoch(local_ts: str) -> int:
    """Epoch seconds for a naive America/New_York timestamp string."""
    return int(pd.Timestamp(local_ts, tz=NY).timestamp())


def _bar(epoch_seconds: int, o: float, h: float, l: float, c: float, v: float) -> BarData:
    bar = BarData()
    bar.date = str(epoch_seconds)
    bar.open = o
    bar.high = h
    bar.low = l
    bar.close = c
    bar.volume = v
    return bar


MARKET_OPEN_EPOCH = _epoch("2026-07-01 09:30:00")


# --- bars_to_dataframe / write_symbol_csv --------------------------------


def test_bars_to_dataframe_converts_epoch_to_eastern_naive_timestamp():
    bars = [_bar(MARKET_OPEN_EPOCH, 100.0, 101.0, 99.5, 100.5, 1000)]

    df = script.bars_to_dataframe("QQQ", bars)

    assert list(df.columns) == list(script.REQUIRED_COLUMNS)
    assert df.iloc[0]["timestamp"] == "2026-07-01 09:30:00"
    assert df.iloc[0]["symbol"] == "QQQ"
    assert df.iloc[0]["open"] == 100.0
    assert df.iloc[0]["volume"] == 1000.0


def test_bars_to_dataframe_empty_list_returns_empty_frame_with_correct_columns():
    df = script.bars_to_dataframe("QQQ", [])

    assert df.empty
    assert list(df.columns) == list(script.REQUIRED_COLUMNS)


def test_write_symbol_csv_writes_expected_filename_and_schema(tmp_path):
    df = script.bars_to_dataframe("NVDA", [_bar(MARKET_OPEN_EPOCH, 1, 2, 0.5, 1.5, 10)])

    path = script.write_symbol_csv(df, tmp_path, "NVDA")

    assert path == tmp_path / "NVDA_1min.csv"
    assert path.exists()
    written = pd.read_csv(path)
    assert list(written.columns) == list(script.REQUIRED_COLUMNS)
    assert written.iloc[0]["symbol"] == "NVDA"


# --- date/duration helpers -------------------------------------------------


def test_duration_str_computes_inclusive_day_count():
    assert script._duration_str(date(2026, 7, 1), date(2026, 7, 1)) == "1 D"
    assert script._duration_str(date(2026, 7, 1), date(2026, 7, 3)) == "3 D"


def test_duration_str_rejects_end_before_start():
    with pytest.raises(ValueError):
        script._duration_str(date(2026, 7, 3), date(2026, 7, 1))


def test_end_date_time_str_format():
    assert script._end_date_time_str(date(2026, 7, 1)) == "20260701-23:59:59"


# --- CLI arg parsing ---------------------------------------------------


def test_parse_args_defaults(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["download_ibkr_bars.py", "--symbols", "QQQ", "NVDA", "--start", "2026-07-01", "--end", "2026-07-01"],
    )

    args = script._parse_args()

    assert args.symbols == ["QQQ", "NVDA"]
    assert args.bar_size == "1 min"
    assert args.output_dir == "data/raw"
    assert args.host == "127.0.0.1"
    assert args.port == 7497
    assert args.client_id == 101


def test_parse_args_overrides(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "download_ibkr_bars.py",
            "--symbols", "TSLA",
            "--start", "2026-07-01",
            "--end", "2026-07-02",
            "--bar-size", "5 mins",
            "--output-dir", "data/custom",
            "--host", "10.0.0.5",
            "--port", "4002",
            "--client-id", "7",
        ],
    )

    args = script._parse_args()

    assert args.bar_size == "5 mins"
    assert args.output_dir == "data/custom"
    assert args.host == "10.0.0.5"
    assert args.port == 4002
    assert args.client_id == 7


# --- download_all (mocked IBKR app) -------------------------------------


class _FakeIBKRApp:
    """Stands in for IBKRHistoricalDataApp -- no sockets, no real event loop."""

    def __init__(self, bars_by_symbol=None, error_symbol=None):
        self.bars_by_symbol = bars_by_symbol or {}
        self.error_symbol = error_symbol
        self.connected = True
        self.disconnected = False
        self.requested_symbols = []
        self.connect_args = None

    def connect(self, host, port, client_id):
        self.connect_args = (host, port, client_id)

    def run(self):
        return  # nothing to read: no real socket exists

    def wait_until_connected(self, timeout):
        return self.connected

    def request_historical_bars(self, symbol, end_date_time, duration, bar_size):
        self.requested_symbols.append(symbol)
        if symbol == self.error_symbol:
            raise script.HistoricalDataRequestError(f"IBKR returned an error for {symbol}: [321] fake error")
        return self.bars_by_symbol.get(symbol, [])

    def disconnect(self):
        self.disconnected = True


def test_download_all_writes_one_csv_per_symbol(tmp_path, monkeypatch):
    fake = _FakeIBKRApp(
        bars_by_symbol={
            "QQQ": [_bar(MARKET_OPEN_EPOCH, 500, 501, 499, 500.5, 5000)],
            "NVDA": [_bar(MARKET_OPEN_EPOCH, 120, 121, 119, 120.5, 800)],
        }
    )
    monkeypatch.setattr(script, "IBKRHistoricalDataApp", lambda: fake)

    paths = script.download_all(
        symbols=["QQQ", "NVDA"],
        start=date(2026, 7, 1),
        end=date(2026, 7, 1),
        bar_size="1 min",
        output_dir=tmp_path,
        host="127.0.0.1",
        port=7497,
        client_id=101,
    )

    assert sorted(p.name for p in paths) == ["NVDA_1min.csv", "QQQ_1min.csv"]
    assert fake.connect_args == ("127.0.0.1", 7497, 101)
    assert fake.disconnected is True
    assert fake.requested_symbols == ["QQQ", "NVDA"]


def test_download_all_raises_connection_error_when_never_connected(tmp_path, monkeypatch):
    fake = _FakeIBKRApp()
    fake.connected = False
    monkeypatch.setattr(script, "IBKRHistoricalDataApp", lambda: fake)

    with pytest.raises(ConnectionError):
        script.download_all(
            symbols=["QQQ"],
            start=date(2026, 7, 1),
            end=date(2026, 7, 1),
            bar_size="1 min",
            output_dir=tmp_path,
            host="127.0.0.1",
            port=7497,
            client_id=101,
        )
    assert fake.disconnected is True  # must still clean up


def test_download_all_propagates_historical_data_request_error(tmp_path, monkeypatch):
    fake = _FakeIBKRApp(error_symbol="QQQ")
    monkeypatch.setattr(script, "IBKRHistoricalDataApp", lambda: fake)

    with pytest.raises(script.HistoricalDataRequestError):
        script.download_all(
            symbols=["QQQ"],
            start=date(2026, 7, 1),
            end=date(2026, 7, 1),
            bar_size="1 min",
            output_dir=tmp_path,
            host="127.0.0.1",
            port=7497,
            client_id=101,
        )
    assert fake.disconnected is True  # must still disconnect cleanly on error


# --- Downstream workflow: no rename step required -----------------------


def test_downloaded_1min_csv_files_validate_and_load_with_no_rename(tmp_path, monkeypatch):
    """The exact workflow this fix targets: files written as
    '{symbol}_1min.csv' by download_all() must validate and load for a
    backtest directly, with no manual rename to '{symbol}_bars.csv'."""
    fake = _FakeIBKRApp(
        bars_by_symbol={
            "QQQ": [_bar(MARKET_OPEN_EPOCH, 500, 501, 499, 500.5, 5000)],
            "NVDA": [_bar(MARKET_OPEN_EPOCH, 120, 121, 119, 120.5, 800)],
        }
    )
    monkeypatch.setattr(script, "IBKRHistoricalDataApp", lambda: fake)

    script.download_all(
        symbols=["QQQ", "NVDA"],
        start=date(2026, 7, 1),
        end=date(2026, 7, 1),
        bar_size="1 min",
        output_dir=tmp_path,
        host="127.0.0.1",
        port=7497,
        client_id=101,
    )

    assert (tmp_path / "QQQ_1min.csv").exists()
    assert (tmp_path / "NVDA_1min.csv").exists()
    assert not (tmp_path / "QQQ_bars.csv").exists()  # no rename ever happens

    validation = validate_directory(tmp_path, confirmation_symbol="QQQ")
    assert validation.is_valid
    assert validation.confirmation_file_found

    bars_by_symbol, qqq_bars = load_backtest_dataset(tmp_path, symbols=["NVDA"], confirmation_symbol="QQQ")
    assert set(bars_by_symbol["NVDA"]["symbol"]) == {"NVDA"}
    assert set(qqq_bars["symbol"]) == {"QQQ"}


# --- main() end-to-end (mocked IBKR app) --------------------------------


def test_main_end_to_end_writes_files_and_prints_report(tmp_path, monkeypatch, capsys):
    fake = _FakeIBKRApp(bars_by_symbol={"QQQ": [_bar(MARKET_OPEN_EPOCH, 500, 501, 499, 500.5, 5000)]})
    monkeypatch.setattr(script, "IBKRHistoricalDataApp", lambda: fake)
    monkeypatch.setattr(
        "sys.argv",
        [
            "download_ibkr_bars.py",
            "--symbols", "QQQ",
            "--start", "2026-07-01",
            "--end", "2026-07-01",
            "--output-dir", str(tmp_path),
        ],
    )

    script.main()

    captured = capsys.readouterr()
    assert "IBKR HISTORICAL DATA DOWNLOAD" in captured.out
    assert (tmp_path / "QQQ_1min.csv").exists()
    assert "wrote" in captured.out


def test_main_rejects_end_before_start(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        ["download_ibkr_bars.py", "--symbols", "QQQ", "--start", "2026-07-03", "--end", "2026-07-01"],
    )

    with pytest.raises(SystemExit) as exc_info:
        script.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "INVALID ARGS" in captured.err


def test_main_rejects_malformed_date(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        ["download_ibkr_bars.py", "--symbols", "QQQ", "--start", "07-01-2026", "--end", "2026-07-01"],
    )

    with pytest.raises(SystemExit) as exc_info:
        script.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "INVALID ARGS" in captured.err


def test_main_reports_download_failure(tmp_path, monkeypatch, capsys):
    fake = _FakeIBKRApp()
    fake.connected = False
    monkeypatch.setattr(script, "IBKRHistoricalDataApp", lambda: fake)
    monkeypatch.setattr(
        "sys.argv",
        [
            "download_ibkr_bars.py",
            "--symbols", "QQQ",
            "--start", "2026-07-01",
            "--end", "2026-07-01",
            "--output-dir", str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        script.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "DOWNLOAD FAILED" in captured.err


# --- Safety guard tests -----------------------------------------------
#
# These tests exist to enforce the historical-data-only scope of this
# script even as it evolves: no live trading, no order placement, no
# order-execution methods, no disallowed broker/venue integrations, and
# no account credential handling anywhere in the module.


def test_no_live_broker_class_or_order_functions_in_module():
    assert not hasattr(script, "LiveBroker")
    for forbidden_name in ("place_order", "buy", "sell", "submit_order", "cancel_order"):
        assert not hasattr(script, forbidden_name)


def test_ibkr_app_class_does_not_define_order_related_methods():
    """EClient (the base class) technically carries IBKR's full order-
    routing surface, but IBKRHistoricalDataApp itself must never
    override, wrap, or call any of it -- only connection/historical-data
    members should appear in its own namespace (not inherited ones)."""
    own_methods = set(vars(script.IBKRHistoricalDataApp).keys())
    forbidden = {
        "placeOrder",
        "cancelOrder",
        "reqAccountUpdates",
        "reqPositions",
        "reqOpenOrders",
        "reqExecutions",
    }
    assert own_methods.isdisjoint(forbidden)


def test_script_source_never_references_order_placement_or_execution():
    source = Path(script.__file__).read_text(encoding="utf-8")
    forbidden_tokens = [
        "placeOrder(",
        "cancelOrder(",
        "reqAccountUpdates(",
        "reqPositions(",
        "reqOpenOrders(",
        "reqExecutions(",
    ]
    for token in forbidden_tokens:
        assert token not in source, f"forbidden token found in download_ibkr_bars.py: {token}"


def test_script_source_never_imports_or_calls_disallowed_brokers_or_venues():
    """Prose mentions like "no Alpaca, no Webull" in the module docstring
    are fine (and expected) -- this checks for actual code-level usage:
    imports, instantiation, or attribute access naming a disallowed
    broker/venue integration."""
    source = Path(script.__file__).read_text(encoding="utf-8")
    forbidden_code_patterns = [
        "import alpaca",
        "from alpaca",
        "import webull",
        "from webull",
        "TradeThePool(",
        "tradethepool",
    ]
    lowered = source.lower()
    for pattern in forbidden_code_patterns:
        assert pattern.lower() not in lowered, f"forbidden code reference found in download_ibkr_bars.py: {pattern}"


def test_script_source_never_references_credential_or_account_env_vars():
    source = Path(script.__file__).read_text(encoding="utf-8")
    for forbidden in ["API_KEY", "API_SECRET", "PASSWORD", "ACCOUNT_ID", "ACCOUNT_NUMBER"]:
        assert forbidden not in source
