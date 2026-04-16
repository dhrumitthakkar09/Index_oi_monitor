"""
data_sources/dhan_source.py — Dhan API data source for OI Monitor.

Architecture (v5 — Option Chain API):
  ┌─────────────────────────────────────────────────────────────────────┐
  │  PRIMARY: Option Chain REST API  POST /v2/optionchain               │
  │  - Called once per index per poll cycle (every 60s)                 │
  │  - Returns: spot LTP, OI per strike, previous_oi per strike         │
  │  - Rate limit: 1 unique request / 3s  →  4 indices × 3s = 12s min  │
  │  - Zero instrument master needed — strikes are in the response      │
  ├─────────────────────────────────────────────────────────────────────┤
  │  SECONDARY: WebSocket  wss://api-feed.dhan.co                       │
  │  - Subscribes to 4 index spot IDs only (IDX_I segment)             │
  │  - Keeps LTP cache fresh between REST poll cycles                   │
  │  - Responses are binary little-endian packets (parsed with struct)  │
  └─────────────────────────────────────────────────────────────────────┘

Why Option Chain API instead of instrument master + Market Feed:
  - Instrument master CSV SEM_INSTRUMENT_NAME values vary between Dhan
    releases; our filter was silently matching 0 contracts.
  - Option Chain API returns ALL strikes in one call with both current OI
    and previous_oi — eliminating the separate candle-API bootstrap.
  - 4 REST calls/minute is well within Dhan rate limits.

Fix history:
  v1: Initial implementation
  v2: FIX-A/B/C/D/E
  v3: FIX-F/G
  v4: FIX-H/I/J/K
  v5 (this file):
      FIX-L: Replaced instrument master + Market Feed OI path with
              Option Chain API — eliminates all "0 contracts indexed"
              and "no data yet" issues at source.
      FIX-M: bootstrap_prev_day reads previous_oi from first Option Chain
              call — no candle API needed, no separate bootstrap thread.
      FIX-N: WS subscription reduced to 4 index spot IDs only; much
              simpler and more reliable.
"""

from __future__ import annotations

import json
import struct
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import requests

import config
from data_sources.base import BaseDataSource
from utils.logger import setup_logger

log = setup_logger("dhan_source")

IST = timezone(timedelta(hours=5, minutes=30))

_BASE_URL          = "https://api.dhan.co"
_OPTION_CHAIN_URL  = f"{_BASE_URL}/v2/optionchain"
_MARKET_FEED_URL   = f"{_BASE_URL}/v2/marketfeed/quote"
_HISTORICAL_URL    = f"{_BASE_URL}/v2/charts/historical"
_WS_URL            = "wss://api-feed.dhan.co"
_EXPIRY_LIST_URL   = f"{_BASE_URL}/v2/optionchain/expirylist"

# Dhan instrument master — public CSV for resolving equity security IDs
_DHAN_SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

_IDX_I  = "IDX_I"    # index underlying segment
_NSE_EQ = "NSE_EQ"   # NSE equity underlying segment (used for stock options)
_NSE_FO = "NSE_FO"
_BSE_FO = "BSE_FO"

# Option Chain rate limit: 1 unique request per 3 seconds
_OC_INTER_REQUEST_DELAY = 3.1   # seconds between option chain calls

# Binary WS response codes
_RC_TICKER     = 2
_RC_QUOTE      = 4
_RC_OI         = 5
_RC_PREV_CLOSE = 6
_RC_FULL       = 8
_RC_DISCONNECT = 50

# Minimum seconds between REST spot refreshes (fallback only)
_SPOT_REST_COOLDOWN = 30


# ── Rate-limiter ──────────────────────────────────────────────────────────────
class _RateLimiter:
    def __init__(self, min_interval: float) -> None:
        self._min  = min_interval
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last
            if elapsed < self._min:
                time.sleep(self._min - elapsed)
            self._last = time.monotonic()

# Separate rate limiters so stock option chain calls don't block the index monitor
_oc_rl       = _RateLimiter(_OC_INTER_REQUEST_DELAY)   # index option chain
_oc_rl_stock = _RateLimiter(_OC_INTER_REQUEST_DELAY)   # stock option chain
_rest_rl     = _RateLimiter(0.25)                      # general REST


def _rest_post(url: str, headers: dict, payload: dict,
               timeout: int = 15, rate_limiter: _RateLimiter = None) -> dict:
    """POST with optional rate-limiting and 429-aware retry.
    Logs full response body on any non-2xx so 400 errors show the Dhan message.
    """
    if rate_limiter is None:
        rate_limiter = _rest_rl
    delays = [2, 5]
    for attempt in range(3):
        rate_limiter.wait()
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if resp.status_code == 429 and attempt < len(delays):
            log.warning("REST 429 — retry in %ds (attempt %d/3)", delays[attempt], attempt + 1)
            time.sleep(delays[attempt])
            continue
        if not resp.ok:
            try:
                body = resp.json()
            except Exception:
                body = resp.text[:500]
            log.warning("REST %d %s  payload=%s  body=%s",
                        resp.status_code, url.split("/")[-1], payload, body)
        resp.raise_for_status()
        return resp.json()
    return {}


def _parse_expiry_to_str(raw: str) -> Optional[str]:
    """Convert any Dhan expiry date → DDMMMYY  e.g. '27MAR26'."""
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%d%b%y").upper()
        except ValueError:
            continue
    return None


class DhanDataSource(BaseDataSource):
    """
    Dhan API data source.

    OI is served from an in-memory cache populated by polling the Option Chain
    API every poll cycle. Spot LTP comes from the WS (primary) or REST fallback.
    """

    def __init__(self) -> None:
        self._token     = config.DHAN_ACCESS_TOKEN
        self._client_id = config.DHAN_CLIENT_ID
        if not self._token or not self._client_id:
            raise ValueError(
                "DHAN_ACCESS_TOKEN and DHAN_CLIENT_ID must be set when DATA_SOURCE=DHAN"
            )

        self._headers = {
            "access-token": self._token,
            "client-id":    self._client_id,
            "Content-Type": "application/json",
            "Accept":       "application/json",
        }

        # ── OI cache: (name, expiry_str, strike, opt_type) → int ─────────────
        self._oi_cache:       Dict[Tuple, int]   = {}
        # ── prev-day OI cache: same key → int (from previous_oi in option chain)
        self._prev_oi_cache:  Dict[Tuple, int]   = {}
        # ── LTP cache: instrument_name → float ───────────────────────────────
        self._ltp_cache:      Dict[str, float]   = {}
        # ── prev-day close price cache: instrument_name → float ──────────────
        self._prev_close_cache: Dict[str, float] = {}
        # ── NSE equity security IDs for stock option chains ───────────────────
        # Populated from Dhan scrip master on start().
        self._stock_eq_ids: Dict[str, str]       = {}   # symbol → security_id
        self._cache_lock = threading.Lock()

        # ── WebSocket ─────────────────────────────────────────────────────────
        self._ws               = None
        self._ws_thread: Optional[threading.Thread] = None
        self._stop_event       = threading.Event()
        self._reconnect_count  = 0
        self._ws_connected_at  = 0.0

        # ── Spot REST debounce ────────────────────────────────────────────────
        self._spot_fetch_lock = threading.Lock()
        self._spot_last_fetch = 0.0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """
        On startup:
          1. Load stock equity security IDs from Dhan scrip master.
          2. Call the Option Chain API for each INDEX (populates OI + prev_day).
          3. Start the WebSocket for real-time index spot prices.
        Stock option chains are fetched lazily on first poll cycle.
        """
        # ── Stock security ID lookup ──────────────────────────────────────────
        try:
            import stock_config as _sc
            self._stock_eq_ids = self._load_stock_eq_ids(set(_sc.STOCK_CONFIG.keys()))
            log.info("DhanDataSource: %d/%d stock security IDs loaded",
                     len(self._stock_eq_ids), len(_sc.STOCK_CONFIG))
        except Exception as exc:
            log.warning("DhanDataSource: stock ID load failed: %s", exc)

        # ── Index option chain pre-fetch ──────────────────────────────────────
        log.info("DhanDataSource: initial Option Chain fetch for indices …")
        for name in config.INDEX_CONFIG:
            try:
                self._fetch_option_chain(name)
            except Exception as exc:
                log.warning("DhanDataSource: initial OC fetch failed for %s: %s", name, exc)

        # ── Prev-day close for each index (for OI pattern classification) ─────
        # Fetched here — before stock OC calls monopolise the rate limiter —
        # so the market feed call has a clear window to succeed.
        log.info("DhanDataSource: fetching prev-day close for indices …")
        for name in config.INDEX_CONFIG:
            try:
                self._fetch_index_prev_close(name)
            except Exception as exc:
                log.warning("DhanDataSource: prev-close fetch failed for %s: %s", name, exc)

        log.info("DhanDataSource: starting WebSocket feed …")
        self._start_ws()

    def stop(self) -> None:
        log.info("DhanDataSource: stopping …")
        self._stop_event.set()
        self._close_ws()

    # ── Stock security ID loader ──────────────────────────────────────────────

    def _load_stock_eq_ids(self, symbols: set) -> Dict[str, str]:
        """
        Download Dhan scrip master CSV and return {symbol: security_id}
        for NSE_EQ instruments matching the given symbols.

        The CSV uses "SEM_TRADING_SYMBOL" like "HDFCBANK-EQ"; we strip suffixes.
        First match per symbol wins (handles duplicates).
        """
        import csv, io
        try:
            resp = requests.get(_DHAN_SCRIP_MASTER_URL, timeout=30)
            resp.raise_for_status()
            reader = csv.DictReader(io.StringIO(resp.text))
            result: Dict[str, str] = {}
            for row in reader:
                # Dhan scrip master changed format: SEM_SEGMENT is now a single
                # letter ('E' for equity) rather than 'NSE_EQ'. Match by exchange
                # + instrument type instead, and restrict to 'EQ' series only.
                if row.get("SEM_EXM_EXCH_ID", "").strip() != "NSE":
                    continue
                if row.get("SEM_INSTRUMENT_NAME", "").strip() != "EQUITY":
                    continue
                if row.get("SEM_SERIES", "").strip() not in ("EQ", ""):
                    continue
                raw = row.get("SEM_TRADING_SYMBOL", "").strip().upper()
                sym = raw.replace("-EQ", "").replace("-BE", "")
                if sym not in symbols or sym in result:
                    continue
                sec_id = row.get("SEM_SMST_SECURITY_ID", "").strip()
                if sec_id:
                    result[sym] = sec_id
            missing = symbols - result.keys()
            if missing:
                log.warning("Stock IDs not found in master (%d): %s",
                            len(missing), sorted(missing)[:10])
            return result
        except Exception as exc:
            log.warning("_load_stock_eq_ids failed: %s", exc)
            return {}

    # ── BaseDataSource interface ───────────────────────────────────────────────

    def get_spot_price(self, name: str) -> float:
        """Return spot LTP from WS cache; fall back to REST."""
        with self._cache_lock:
            price = self._ltp_cache.get(name, 0.0)
        if price > 0:
            return price
        self._maybe_fetch_all_spot_rest()
        with self._cache_lock:
            return self._ltp_cache.get(name, 0.0)

    def get_option_oi(self, name: str, expiry: str, strike: int, opt_type: str) -> int:
        key = (name, expiry, strike, opt_type)
        with self._cache_lock:
            return self._oi_cache.get(key, 0)

    def get_prev_close(self, name: str) -> float:
        """Return previous trading day's closing spot price for an index."""
        with self._cache_lock:
            return self._prev_close_cache.get(name, 0.0)

    def batch_refresh_oi(self, requests_list: List[Tuple[str, str, int, str]]) -> None:
        """
        Poll the Option Chain API for each unique (name, expiry) pair in requests_list.
        The expiry string comes directly from monitor state (e.g. "30MAR2026") so the
        OI cache keys exactly match what get_option_oi() will be called with.
        """
        if not requests_list:
            return
        # Collect unique (name, monitor_expiry) pairs — one OC call per pair
        seen: set = set()
        for name, monitor_expiry, *_ in requests_list:
            key = (name, monitor_expiry)
            if key not in seen:
                seen.add(key)
                try:
                    self._fetch_option_chain(name, monitor_expiry)
                except Exception as exc:
                    log.warning("batch_refresh_oi: OC fetch failed for %s: %s", name, exc)

    def fetch_prev_day_oi_from_candles(
        self,
        requests_list: List[Tuple[str, str, int, str]],
    ) -> Dict[Tuple, int]:
        """
        FIX-M: Return previous_oi values already in cache from the initial
        Option Chain fetch done in start(). No candle API needed.
        """
        result: Dict[Tuple, int] = {}
        with self._cache_lock:
            for req in requests_list:
                prev_oi = self._prev_oi_cache.get(req, 0)
                if prev_oi > 0:
                    result[req] = prev_oi
        log.info("fetch_prev_day_oi_from_candles: %d/%d entries from OC cache",
                 len(result), len(requests_list))
        return result

    # ── Option Chain API ──────────────────────────────────────────────────────

    def _get_nearest_expiry_from_dhan(self, name: str) -> Optional[str]:
        """
        Fetch the real nearest expiry date from Dhan's Expiry List API.
        Works for both indices (IDX_I segment) and stocks (NSE_EQ segment).
        Returns "YYYY-MM-DD" or None on failure.
        """
        is_index = name in config.INDEX_CONFIG
        if is_index:
            sec_id = config.INDEX_CONFIG[name].get("dhan_security_id")
            seg    = _IDX_I
        else:
            sec_id = self._stock_eq_ids.get(name)
            seg    = _NSE_EQ

        if not sec_id:
            return None
        try:
            data = _rest_post(
                _EXPIRY_LIST_URL, self._headers,
                {"UnderlyingScrip": int(sec_id), "UnderlyingSeg": seg},
                timeout=10, rate_limiter=_rest_rl,
            )
            expiries = data.get("data", [])
            if not expiries:
                log.warning("_get_nearest_expiry_from_dhan(%s): empty expiry list", name)
                return None
            log.debug("%s expiry list: %s", name, expiries[:6])
            today = datetime.now(IST).date()
            for exp_str in sorted(expiries):
                try:
                    exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                    if exp_date >= today:
                        log.info("%s: nearest expiry from Dhan = %s", name, exp_str)
                        return exp_str
                except ValueError:
                    continue
        except Exception as exc:
            log.warning("_get_nearest_expiry_from_dhan(%s): %s", name, exc)
        return None

    def _fetch_option_chain(self, name: str, monitor_expiry: Optional[str] = None) -> None:
        """
        Call POST /v2/optionchain for one instrument (index or stock) and update caches.

        Works for:
          - Indices (IDX_I segment, sec_id from config.INDEX_CONFIG)
          - Stocks  (NSE_EQ segment, sec_id from _stock_eq_ids loaded from scrip master)

        monitor_expiry: authoritative cache key coming from state.expiry in
          batch_refresh_oi. When None (startup), derived from Dhan expiry list.

        Dhan's actual expiry date is always fetched from the Expiry List API
        to avoid 400 errors from locally-computed wrong dates.
        """
        is_index = name in config.INDEX_CONFIG

        if is_index:
            sec_id        = config.INDEX_CONFIG[name].get("dhan_security_id")
            underlying_seg = _IDX_I
            rl            = _oc_rl
            expiry_type   = config.INDEX_CONFIG[name].get("expiry_type", "monthly")
        else:
            sec_id        = self._stock_eq_ids.get(name)
            underlying_seg = _NSE_EQ
            rl            = _oc_rl_stock
            expiry_type   = "monthly"   # all stock options are monthly

        if not sec_id:
            log.debug("_fetch_option_chain: no security ID for %s — skipping", name)
            return

        # Always get the real Dhan expiry date for the API call
        expiry_api = self._get_nearest_expiry_from_dhan(name)
        if not expiry_api:
            from utils.expiry_utils import get_current_expiry
            expiry_date = get_current_expiry(name, expiry_type)
            expiry_api  = expiry_date.strftime("%Y-%m-%d")
            log.warning("%s: expiry list API failed, using local fallback %s", name, expiry_api)

        # Cache key: monitor_expiry if provided, else derive from Dhan date
        if monitor_expiry:
            expiry_str = monitor_expiry
        else:
            try:
                expiry_str = datetime.strptime(expiry_api, "%Y-%m-%d").strftime("%d%b%Y").upper()
            except ValueError:
                log.warning("_fetch_option_chain: cannot parse expiry %r for %s", expiry_api, name)
                return

        log.info("%s: OC fetch  seg=%s  api_expiry=%s  cache_key=%s",
                 name, underlying_seg, expiry_api, expiry_str)

        # Purge stale cache entries for this name with a different expiry
        with self._cache_lock:
            stale = [k for k in self._oi_cache if k[0] == name and k[1] != expiry_str]
            for k in stale:
                del self._oi_cache[k]
                self._prev_oi_cache.pop(k, None)
            if stale:
                log.debug("%s: purged %d stale cache entries (old expiry)", name, len(stale))

        payload = {
            "UnderlyingScrip": int(sec_id),
            "UnderlyingSeg":   underlying_seg,
            "Expiry":          expiry_api,
        }

        try:
            data = _rest_post(
                _OPTION_CHAIN_URL, self._headers, payload,
                timeout=15, rate_limiter=rl,
            )
        except Exception as exc:
            log.warning("Option Chain API failed for %s: %s", name, exc)
            return

        oc_data = data.get("data", {})
        if not oc_data:
            log.warning("Option Chain: empty response for %s expiry=%s", name, expiry_api)
            return

        # Spot LTP from option chain response
        spot = float(oc_data.get("last_price", 0) or 0)
        if spot > 0:
            with self._cache_lock:
                self._ltp_cache[name] = spot

        # Parse strike-wise OI
        oc          = oc_data.get("oc", {})
        updated_oi  = 0
        updated_poi = 0

        with self._cache_lock:
            for strike_str, strike_data in oc.items():
                try:
                    strike = int(float(strike_str))
                except ValueError:
                    continue

                for opt_type_lower, leg_key in [("ce", "CE"), ("pe", "PE")]:
                    leg = strike_data.get(opt_type_lower, {})
                    if not leg:
                        continue

                    key = (name, expiry_str, strike, leg_key)

                    oi = int(leg.get("oi", 0) or 0)
                    if oi > 0:
                        self._oi_cache[key] = oi
                        updated_oi += 1

                    prev_oi = int(leg.get("previous_oi", 0) or 0)
                    if prev_oi > 0:
                        self._prev_oi_cache[key] = prev_oi
                        updated_poi += 1

        # Fetch prev-day close OUTSIDE the lock — the fetch helper acquires
        # the same lock internally to write the result (deadlock if nested).
        with self._cache_lock:
            need_prev_close = name not in self._prev_close_cache or self._prev_close_cache[name] <= 0
        if need_prev_close:
            if is_index:
                self._fetch_index_prev_close(name)
            elif sec_id and spot > 0:
                self._fetch_prev_close_historical(name, str(sec_id), _NSE_EQ)

        log.info("Option Chain %s expiry=%s: spot=%.2f  OI strikes=%d  prevOI strikes=%d",
                 name, expiry_str, spot, updated_oi // 2, updated_poi // 2)
        if updated_oi == 0:
            log.warning(
                "%s: 0 OI entries stored — possible expiry mismatch "
                "(expiry_str=%r, seg=%s). Check scrip master / expiry list.",
                name, expiry_str, underlying_seg,
            )

    # ── Spot & Prev-close REST helpers ───────────────────────────────────────

    def _fetch_index_prev_close(self, name: str) -> None:
        """Fetch prev-day close for an index via Historical Chart API."""
        sec_id = config.INDEX_CONFIG.get(name, {}).get("dhan_security_id")
        if not sec_id:
            return
        self._fetch_prev_close_historical(name, str(sec_id), _IDX_I, instrument="INDEX")

    def _fetch_prev_close_historical(
        self,
        name:       str,
        sec_id:     str,
        segment:    str,
        instrument: str = "EQUITY",
    ) -> None:
        """
        Fetch the previous trading day's closing price using the Dhan Historical
        Chart API (POST /v2/charts/historical).

        Works for both indices (segment=IDX_I, instrument=INDEX) and equity
        stocks (segment=NSE_EQ, instrument=EQUITY).  The API only returns
        completed candles, so closes[-1] is always the last finished trading day.
        """
        try:
            today     = datetime.now(IST).strftime("%Y-%m-%d")
            from_date = (datetime.now(IST).date() - timedelta(days=5)).strftime("%Y-%m-%d")
            payload   = {
                "securityId":      sec_id,
                "exchangeSegment": segment,
                "instrument":      instrument,
                "expiryCode":      0,
                "fromDate":        from_date,
                "toDate":          today,
            }
            data   = _rest_post(_HISTORICAL_URL, self._headers, payload, timeout=10)
            closes = data.get("close") or []
            if not closes:
                log.debug("_fetch_prev_close_historical(%s): empty response", name)
                return
            prev_close = float(closes[-1])
            if prev_close > 0:
                with self._cache_lock:
                    self._prev_close_cache[name] = prev_close
                log.debug("Prev close %s = %.2f", name, prev_close)
        except Exception as exc:
            log.debug("_fetch_prev_close_historical(%s): %s", name, exc)

    def _maybe_fetch_all_spot_rest(self) -> None:
        """Debounced batch spot price fetch via Market Feed API."""
        if time.monotonic() - self._spot_last_fetch < _SPOT_REST_COOLDOWN:
            return
        acquired = self._spot_fetch_lock.acquire(blocking=True, timeout=10)
        if not acquired:
            return
        try:
            if time.monotonic() - self._spot_last_fetch < _SPOT_REST_COOLDOWN:
                return
            self._fetch_all_spot_rest()
            self._spot_last_fetch = time.monotonic()
        finally:
            self._spot_fetch_lock.release()

    def _fetch_all_spot_rest(self) -> None:
        """Fetch LTP for all indices in ONE Market Feed REST call."""
        payload: Dict[str, List[str]] = {}
        sid_to_name: Dict[str, str]   = {}
        for idx_name, idx_cfg in config.INDEX_CONFIG.items():
            sec_id = idx_cfg.get("dhan_security_id")
            if sec_id:
                payload.setdefault(_IDX_I, []).append(str(sec_id))
                sid_to_name[str(sec_id)] = idx_name
        if not payload:
            return
        try:
            data    = _rest_post(_MARKET_FEED_URL, self._headers, {"data": payload})
            records = (data.get("data") or {}).get(_IDX_I, {})
            updated = []
            with self._cache_lock:
                for sid, rec in (records or {}).items():
                    nm = sid_to_name.get(str(sid))
                    if not nm:
                        continue
                    ltp = float(rec.get("last_price", rec.get("ltp", 0)) or 0)
                    if ltp > 0:
                        self._ltp_cache[nm] = ltp
                        updated.append(f"{nm}={ltp:.2f}")
            if updated:
                log.info("Spot REST: %s", "  ".join(updated))
        except Exception as exc:
            log.warning("_fetch_all_spot_rest failed: %s", exc)

    # ── WebSocket (spot LTP only) ─────────────────────────────────────────────

    def _start_ws(self) -> None:
        self._ws_thread = threading.Thread(
            target=self._ws_run_loop, name="DhanWS", daemon=True
        )
        self._ws_thread.start()

    def _close_ws(self) -> None:
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def _ws_run_loop(self) -> None:
        try:
            import websocket as _  # noqa: F401
        except ImportError:
            log.warning(
                "DhanWS: websocket-client not installed — spot prices via REST only.\n"
                "  Fix: ensure 'websocket-client>=1.7.0' is in requirements.txt."
            )
            return

        while not self._stop_event.is_set():
            if self._reconnect_count >= config.WS_MAX_RECONNECT_ATTEMPTS:
                log.error("DhanWS: max reconnect attempts reached — stopping.")
                break
            try:
                self._reconnect_count += 1
                log.info("DhanWS: connecting (attempt %d) …", self._reconnect_count)
                self._ws_connect_and_run()
                if self._stop_event.is_set():
                    break
            except Exception as exc:
                log.warning("DhanWS: error: %s", exc)

            # Reset counter only after a stable connection (>30s)
            if time.monotonic() - self._ws_connected_at > 30:
                self._reconnect_count = 0

            delay = min(config.WS_RECONNECT_DELAY * (2 ** (self._reconnect_count - 1)), 60)
            log.info("DhanWS: reconnecting in %ds …", delay)
            self._stop_event.wait(timeout=delay)
        log.info("DhanWS: loop exited")

    def _ws_connect_and_run(self) -> None:
        """
        FIX-N: Subscribe only to 4 index spot IDs (IDX_I segment).
        Option OI now comes from the Option Chain REST API, not WS.
        """
        import websocket as ws_lib

        ws_url = (
            f"{_WS_URL}"
            f"?version=2"
            f"&token={self._token}"
            f"&clientId={self._client_id}"
            f"&authType=2"
        )

        idx_ids = [
            str(cfg["dhan_security_id"])
            for cfg in config.INDEX_CONFIG.values()
            if cfg.get("dhan_security_id")
        ]

        sub_msg = {
            "RequestCode":     15,
            "InstrumentCount": len(idx_ids),
            "InstrumentList":  [
                {"ExchangeSegment": "IDX_I", "SecurityId": sid}
                for sid in idx_ids
            ],
        }

        def _on_open(app):
            self._ws_connected_at = time.monotonic()
            log.info("DhanWS: connected — subscribing %d index spots …", len(idx_ids))
            time.sleep(0.5)
            app.send(json.dumps(sub_msg))

        def _on_msg(app, raw):
            try:
                if isinstance(raw, (bytes, bytearray)):
                    self._parse_binary_packet(raw)
                else:
                    log.debug("DhanWS text: %s", str(raw)[:200])
            except Exception as exc:
                log.debug("DhanWS parse error: %s", exc)

        def _on_err(app, err):
            log.warning("DhanWS error: %s", err)

        def _on_close(app, code, msg):
            log.info("DhanWS closed (code=%s)", code)

        ws_app = ws_lib.WebSocketApp(
            ws_url,
            on_open=_on_open, on_message=_on_msg,
            on_error=_on_err, on_close=_on_close,
        )
        self._ws = ws_app
        ws_app.run_forever(ping_interval=25, ping_timeout=10, skip_utf8_validation=True)

    def _parse_binary_packet(self, data: bytes) -> None:
        """
        Parse Dhan binary WS response (little-endian).
        Header: response_code(u8), msg_len(i16), exchange(u8), security_id(i32)
        We only care about LTP for the 4 index spot IDs.
        """
        if len(data) < 8:
            return
        try:
            rc, _msg_len, _seg, sec_id = struct.unpack_from("<BhBi", data, 0)
        except struct.error:
            return

        sec_id_str = str(sec_id)

        # Ticker (code 2) or Quote (code 4) or Full (code 8): LTP at bytes 8-11
        if rc in (_RC_TICKER, _RC_QUOTE, _RC_FULL) and len(data) >= 12:
            ltp = struct.unpack_from("<f", data, 8)[0]
            if ltp > 0:
                with self._cache_lock:
                    for idx_name, idx_cfg in config.INDEX_CONFIG.items():
                        if str(idx_cfg.get("dhan_security_id", "")) == sec_id_str:
                            self._ltp_cache[idx_name] = ltp
                            break

        elif rc == _RC_DISCONNECT and len(data) >= 10:
            reason = struct.unpack_from("<h", data, 8)[0]
            log.warning("DhanWS: server disconnect reason=%d", reason)
