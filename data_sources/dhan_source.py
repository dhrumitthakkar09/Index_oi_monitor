"""
data_sources/dhan_source.py — Dhan API adapter.

Uses:
  - REST  → authenticate, fetch spot, fetch option chain OI
  - WebSocket (DhanSDK) → subscribe to live ticks

Requirements:
  pip install dhanhq

Environment variables:
  DHAN_ACCESS_TOKEN, DHAN_CLIENT_ID
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import config

import stock_config as _stock_config


def _get_instrument_cfg(name: str) -> dict:
    """Resolve instrument config from INDEX_CONFIG or STOCK_CONFIG."""
    combined = {**config.INDEX_CONFIG, **_stock_config.STOCK_CONFIG}
    if name not in combined:
        raise KeyError(f"'{name}' not found in INDEX_CONFIG or STOCK_CONFIG.")
    return combined[name]

from data_sources.base import BaseDataSource
from utils.logger import setup_logger

log = setup_logger("dhan_source")


class DhanDataSource(BaseDataSource):
    """
    Dhan API data source with WebSocket live feed support.
    """

    def __init__(self) -> None:
        self._client:     Optional[Any] = None
        self._ws:         Optional[Any] = None

        # Live caches updated by WS ticks
        self._oi_cache:   Dict[Tuple, int]   = {}
        self._spot_cache: Dict[str, float]   = {}

        self._connected  = False
        self._started    = False              # idempotent guard
        self._start_lock = threading.Lock()   # prevent concurrent starts
        self._stop_event = threading.Event()

    # ────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ────────────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """
        Initialise client and connect WebSocket.
        Idempotent — only the first call does work; subsequent calls are no-ops.
        """
        with self._start_lock:
            if self._started:
                log.debug("DhanDataSource.start() called again — already running, skipping")
                return
            self._init_client()
            self._connect_ws()
            self._started = True
            log.info("DhanDataSource started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._ws:
            try:
                self._ws.disconnect()
            except Exception:
                pass
        self._started = False
        log.info("DhanDataSource stopped")

    def is_ready(self) -> bool:
        return self._client is not None

    # ────────────────────────────────────────────────────────────────────────
    # Public API
    # ────────────────────────────────────────────────────────────────────────

    def get_spot_price(self, index_name: str) -> float:
        if cached := self._spot_cache.get(index_name):
            return cached
        return self._fetch_spot_rest(index_name)

    def get_option_oi(
        self,
        index_name:  str,
        expiry:      str,
        strike:      int,
        option_type: str,
    ) -> int:
        key = (index_name, expiry, strike, option_type)
        if key in self._oi_cache:
            return self._oi_cache[key]
        return self._fetch_oi_rest(index_name, expiry, strike, option_type)

    # ────────────────────────────────────────────────────────────────────────
    # Internal
    # ────────────────────────────────────────────────────────────────────────

    def _init_client(self) -> None:
        try:
            from dhanhq import dhanhq
            self._client = dhanhq(
                client_id=config.DHAN_CLIENT_ID,
                access_token=config.DHAN_ACCESS_TOKEN,
            )
            log.info("Dhan client initialised")
        except ImportError:
            log.error("dhanhq not installed. Run: pip install dhanhq")
            raise
        except Exception as exc:
            log.error("Dhan init failed: %s", exc)
            raise

    def _connect_ws(self) -> None:
        """Connect Dhan WebSocket for live quotes."""
        try:
            from dhanhq import marketfeed

            def on_message(data: Dict) -> None:
                self._handle_ws_tick(data)

            def on_connect() -> None:
                log.info("Dhan WS connected")
                self._connected = True

            def on_disconnect() -> None:
                log.warning("Dhan WS disconnected")
                self._connected = False
                if not self._stop_event.is_set():
                    self._schedule_reconnect()

            self._ws = marketfeed.DhanFeed(
                client_id=config.DHAN_CLIENT_ID,
                access_token=config.DHAN_ACCESS_TOKEN,
                on_message=on_message,
                on_connect=on_connect,
                on_disconnect=on_disconnect,
            )
            ws_thread = threading.Thread(target=self._ws.run_forever, daemon=True)
            ws_thread.start()

        except ImportError:
            log.warning("Dhan marketfeed not available; REST-only mode")
        except Exception as exc:
            log.error("Dhan WS connect failed: %s", exc)

    def _schedule_reconnect(self) -> None:
        if self._stop_event.is_set():
            return

        def reconnect():
            for attempt in range(1, config.WS_MAX_RECONNECT_ATTEMPTS + 1):
                if self._stop_event.is_set():
                    return
                wait = config.WS_RECONNECT_DELAY * attempt
                log.info("Dhan WS reconnect %d/%d in %ds …",
                         attempt, config.WS_MAX_RECONNECT_ATTEMPTS, wait)
                time.sleep(wait)
                try:
                    self._connect_ws()
                    return
                except Exception as exc:
                    log.error("Reconnect %d failed: %s", attempt, exc)
            log.critical("Dhan: all reconnect attempts exhausted")

        threading.Thread(target=reconnect, daemon=True).start()

    def _handle_ws_tick(self, data: Dict) -> None:
        """Update live OI cache from Dhan tick."""
        try:
            security_id  = str(data.get("security_id", ""))
            oi           = int(data.get("OI", 0))
            ltp          = float(data.get("LTP", 0))
            key          = self._security_id_to_key(security_id)
            if key:
                self._oi_cache[key] = oi
        except Exception:
            pass

    def _security_id_to_key(self, security_id: str) -> Optional[Tuple]:
        """
        Map Dhan security_id → (index, expiry, strike, option_type).
        Requires pre-loaded Dhan instrument master.
        """
        return None   # TODO: build from Dhan instrument CSV

    def _fetch_spot_rest(self, index_name: str) -> float:
        """Fetch index spot via Dhan REST."""
        try:
            cfg = _get_instrument_cfg(index_name)
            symbol     = cfg["dhan_symbol"]
            # Dhan index LTP — using a known security_id map
            INDEX_TOKEN = {
                "NIFTY": "13",
                "BANKNIFTY": "25",
                "SENSEX": "1",
                "MIDCAPSELECT": "288009",
            }
            token  = INDEX_TOKEN.get(index_name, "13")
            resp   = self._client.intraday_daily_minute_charts(
                security_id=token,
                exchange_segment="IDX_I",
                instrument_type="INDEX",
            )
            price = float(resp["data"][-1]["close"]) if resp.get("data") else 0.0
            self._spot_cache[index_name] = price
            return price
        except Exception as exc:
            log.error("Dhan REST spot failed %s: %s", index_name, exc)
            return 0.0

    def _fetch_oi_rest(
        self,
        index_name:  str,
        expiry:      str,
        strike:      int,
        option_type: str,
    ) -> int:
        """
        Dhan option chain REST call.
        Dhan expiry format: 'YYYY-MM-DD'
        Our format:         'DDMMMYYYY'
        """
        try:
            from datetime import datetime
            cfg = _get_instrument_cfg(index_name)
            symbol    = cfg["dhan_symbol"]
            expiry_dt = datetime.strptime(expiry, "%d%b%Y")
            expiry_dhan = expiry_dt.strftime("%Y-%m-%d")

            resp = self._client.option_chain(
                optionality=option_type,
                underlying_scrip=symbol,
                expiry=expiry_dhan,
                strike_price=strike,
            )
            if resp.get("status") == "success":
                data = resp.get("data", {})
                return int(data.get("OI", 0))
            return 0
        except Exception as exc:
            log.error("Dhan OI REST failed %s %s %d %s: %s",
                      index_name, expiry, strike, option_type, exc)
            return 0

    def subscribe(self, security_ids: List[str], exchange: str = "NSE_FO") -> None:
        """Subscribe to live OI feed for instruments."""
        if not self._ws or not self._connected:
            log.warning("Dhan WS not connected, skipping subscription")
            return
        try:
            instruments = [(exchange, sid) for sid in security_ids]
            self._ws.subscribe_symbols(instruments)
            log.info("Dhan: subscribed to %d instruments", len(instruments))
        except Exception as exc:
            log.error("Dhan subscribe failed: %s", exc)
