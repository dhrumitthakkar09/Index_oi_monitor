"""
stock_monitor.py — F&O Stock OI Monitor.

Uses stock_config.STOCK_CONFIG (monthly expiry, 100% threshold for all stocks).
Shares the same data source instance as the index monitor.
Runs in a background daemon thread from main.py.

Poll cycle is intentionally long (STOCK_POLL_INTERVAL_SECONDS, default 600s)
because fetching option chains for 200+ stocks at Dhan's 3s rate limit
takes ~620s per full cycle.
"""

from __future__ import annotations

from data_sources.base import BaseDataSource
from monitor import BaseOIMonitor
import stock_config
import config


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
            poll_interval=config.STOCK_POLL_INTERVAL_SECONDS,
        )
