"""
stock_monitor.py — F&O Stock OI Monitor.

Extends BaseOIMonitor with stock_config.STOCK_CONFIG:
  - Monthly expiry
  - OI change alert threshold: ≥ 100%
  - Monitors ATM, 1 ITM, 1 OTM for both CE and PE

Usage (standalone):
    from data_sources import get_data_source
    from stock_monitor import StockOIMonitor
    monitor = StockOIMonitor(get_data_source())
    monitor.start()   # blocking

Usage (threaded, alongside index monitor — see main.py):
    t = threading.Thread(target=monitor.start, daemon=True)
    t.start()
"""

from __future__ import annotations

from data_sources.base import BaseDataSource
from monitor import BaseOIMonitor
import stock_config


class StockOIMonitor(BaseOIMonitor):
    """
    F&O Stock OI Monitor.

    Uses stock_config.STOCK_CONFIG — add/remove stocks there without
    touching any other file.
    """

    def __init__(self, data_source: BaseDataSource) -> None:
        super().__init__(
            data_source=data_source,
            instrument_config=stock_config.STOCK_CONFIG,
            label="Stock OI Monitor",
        )
