"""
data_sources/yahoo_source.py — Yahoo Finance adapter via yfinance.

Supports both index instruments (config.INDEX_CONFIG) and F&O stocks
(stock_config.STOCK_CONFIG) using the same interface.

Limitations:
  - yfinance option data has a ~15-minute delay (NSE public data).
  - OI values match NSE's end-of-day option chain, not live tick data.
  - Use ANGEL or DHAN source for real-time OI during market hours.
"""

from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

import config
from data_sources.base import BaseDataSource
from utils.logger import setup_logger

log = setup_logger("yahoo_source")

_SPOT_CACHE_TTL  = 30   # seconds
_CHAIN_CACHE_TTL = 60   # seconds


def _get_instrument_cfg(name: str) -> dict:
    """
    Look up instrument config by name from INDEX_CONFIG or STOCK_CONFIG.
    Raises KeyError with a helpful message if not found.
    """
    import stock_config
    combined = {**config.INDEX_CONFIG, **stock_config.STOCK_CONFIG}
    if name not in combined:
        raise KeyError(
            f"'{name}' not found in INDEX_CONFIG or STOCK_CONFIG.\n"
            f"  Available: {sorted(combined.keys())}"
        )
    return combined[name]


class YahooDataSource(BaseDataSource):
    """Fetches index/stock spot and option OI from Yahoo Finance."""

    def __init__(self) -> None:
        # (yahoo_symbol) → (price, fetch_time)
        self._spot_cache: Dict[str, Tuple[float, float]] = {}
        # (yahoo_symbol, expiry_str, option_type) → (DataFrame, fetch_time)
        self._chain_cache: Dict[Tuple, Tuple[object, float]] = {}

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def get_spot_price(self, name: str) -> float:
        """Return current spot/LTP for an index or stock by config key."""
        try:
            cfg    = _get_instrument_cfg(name)
            symbol = cfg["yahoo_symbol"]
            return self._fetch_spot(symbol)
        except Exception as exc:
            log.error("get_spot_price failed for %s: %s", name, exc)
            return 0.0

    def get_option_oi(
        self,
        name:        str,
        expiry:      str,    # "27FEB2026"
        strike:      int,
        option_type: str,    # "CE" | "PE"
    ) -> int:
        """Return Open Interest for the given option contract."""
        try:
            cfg    = _get_instrument_cfg(name)
            symbol = cfg["yahoo_symbol"]
            return self._fetch_oi(symbol, expiry, strike, option_type)
        except Exception as exc:
            log.error("get_option_oi failed %s %s %d %s: %s",
                      name, expiry, strike, option_type, exc)
            return 0

    # ─────────────────────────────────────────────────────────────────────────
    # Internal — spot
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_spot(self, yahoo_symbol: str) -> float:
        now    = time.time()
        cached = self._spot_cache.get(yahoo_symbol)
        if cached and (now - cached[1]) < _SPOT_CACHE_TTL:
            return cached[0]

        try:
            import yfinance as yf
            ticker = yf.Ticker(yahoo_symbol)
            price  = (
                ticker.fast_info.get("lastPrice")
                or ticker.fast_info.get("regularMarketPrice")
            )
            if not price:
                hist  = ticker.history(period="1d", interval="1m")
                price = float(hist["Close"].iloc[-1]) if not hist.empty else 0.0
            price = float(price)
            self._spot_cache[yahoo_symbol] = (price, now)
            log.debug("Spot %s = %.2f", yahoo_symbol, price)
            return price
        except Exception as exc:
            log.error("_fetch_spot failed %s: %s", yahoo_symbol, exc)
            return cached[0] if cached else 0.0

    # ─────────────────────────────────────────────────────────────────────────
    # Internal — option chain + OI
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_oi(
        self,
        yahoo_symbol: str,
        expiry:       str,
        strike:       int,
        option_type:  str,
    ) -> int:
        chain_df = self._get_chain(yahoo_symbol, expiry, option_type)
        if chain_df is None or chain_df.empty:
            return 0
        df = chain_df.copy()
        df["_diff"] = (df["strike"] - strike).abs()
        row = df.loc[df["_diff"].idxmin()]
        oi  = int(row.get("openInterest", 0) or 0)
        log.debug("OI %s %s %s %d = %d", yahoo_symbol, expiry, option_type, strike, oi)
        return oi

    def _get_chain(
        self,
        yahoo_symbol: str,
        expiry:       str,
        option_type:  str,
    ):
        """
        Fetch and cache the option chain DataFrame.
        Matches our 'DDMMMYYYY' expiry string to the closest yfinance expiry.
        """
        from datetime import datetime

        cache_key = (yahoo_symbol, expiry, option_type)
        now       = time.time()
        cached    = self._chain_cache.get(cache_key)
        if cached and (now - cached[1]) < _CHAIN_CACHE_TTL:
            return cached[0]

        try:
            import yfinance as yf
            ticker      = yf.Ticker(yahoo_symbol)
            yf_expiries = ticker.options
            if not yf_expiries:
                log.warning("No option expiries for %s", yahoo_symbol)
                return None

            target_dt = datetime.strptime(expiry, "%d%b%Y")
            best      = min(
                yf_expiries,
                key=lambda e: abs((datetime.strptime(e, "%Y-%m-%d") - target_dt).days),
            )
            chain = ticker.option_chain(best)
            df    = chain.calls if option_type == "CE" else chain.puts

            self._chain_cache[cache_key] = (df, now)
            log.debug("Fetched chain %s %s expiry=%s (matched %s)",
                      yahoo_symbol, option_type, expiry, best)
            return df
        except Exception as exc:
            log.error("_get_chain failed %s %s: %s", yahoo_symbol, expiry, exc)
            return None

    def start(self) -> None:
        log.info("YahooDataSource ready (REST/poll mode)")

    def stop(self) -> None:
        log.info("YahooDataSource stopped")
