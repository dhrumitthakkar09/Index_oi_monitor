"""
data_sources/__init__.py — Factory that returns the configured data source.
"""

from __future__ import annotations

from data_sources.base import BaseDataSource


def get_data_source() -> BaseDataSource:
    """
    Return the appropriate data source adapter based on config.DATA_SOURCE.
    Config is imported lazily here so the project root is already on sys.path
    by the time main.py calls this function.
    """
    import config                                   # lazy — path already set by main.py
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
            f"Unknown DATA_SOURCE '{config.DATA_SOURCE}'. "
            "Valid options: YAHOO | ANGEL | DHAN"
        )
