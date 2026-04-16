"""
data_sources/__init__.py — Data source factory.

Returns the correct adapter based on config.DATA_SOURCE.
Supported values: "YAHOO" | "ANGEL" | "DHAN"
"""

from __future__ import annotations

import config
from data_sources.base import BaseDataSource


def get_data_source() -> BaseDataSource:
    source = config.DATA_SOURCE.upper()

    if source == "YAHOO":
        from data_sources.yahoo_source import YahooDataSource
        return YahooDataSource()

    elif source == "ANGEL":
        from data_sources.angel_source import AngelDataSource
        return AngelDataSource()

    elif source == "DHAN":
        from data_sources.dhan_source import DhanDataSource
        return DhanDataSource()

    else:
        raise ValueError(
            f"Unknown DATA_SOURCE={source!r}. "
            f"Valid options: YAHOO | ANGEL | DHAN"
        )
