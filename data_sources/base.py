"""
data_sources/base.py — Abstract base class for all data source adapters.

Every adapter must implement:
    get_spot_price(index_name)  → float
    get_option_oi(index_name, expiry, strike, option_type)  → int
    start() / stop()            → lifecycle hooks
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class OIRecord:
    index:       str
    expiry:      str      # e.g. "27FEB2026"
    strike:      int
    option_type: str      # "CE" | "PE"
    oi:          int
    ltp:         Optional[float] = None


class BaseDataSource(ABC):
    """
    Abstract data source.  Concrete adapters override the abstract methods.
    """

    @abstractmethod
    def get_spot_price(self, index_name: str) -> float:
        """Return the current spot/index price."""
        ...

    @abstractmethod
    def get_option_oi(
        self,
        index_name:  str,
        expiry:      str,
        strike:      int,
        option_type: str,
    ) -> int:
        """Return current Open Interest for the given contract."""
        ...

    def start(self) -> None:
        """Optional lifecycle hook (e.g. open WebSocket connection)."""

    def stop(self) -> None:
        """Optional lifecycle hook (e.g. close WebSocket connection)."""

    def is_ready(self) -> bool:
        """Return True when the data source is connected and ready."""
        return True

    def bootstrap_spot(self, name: str) -> float:
        """
        Optional: fetch spot for a symbol before any OI data has been polled.

        Default implementation delegates to get_spot_price().
        Broker adapters (e.g. Angel One) override this to use a special
        zero-strike option chain call that returns underlyingValue without
        needing a known ATM strike.

        Returns 0.0 if spot cannot be determined.
        """
        return self.get_spot_price(name)
