"""
backtesting/

Historical backtesting for the liquidity sweep strategy. Everything in
this package operates on local CSV files and PaperBroker-simulated
fills only:
  - No network access.
  - No IBKR, Trade The Pool, or any other broker/prop-firm integration.
  - No live order placement of any kind.
  - No credentials, API keys, or secrets are read or required.

See src/backtesting/data_loader.py, src/backtesting/engine.py, and
src/backtesting/metrics.py.
"""

from __future__ import annotations
