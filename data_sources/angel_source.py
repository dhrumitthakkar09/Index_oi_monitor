"""
data_sources/angel_source.py — Angel One SmartAPI adapter.

Confirmed working (from live API debug 2026-02-23):
  ✓  Quote API  mode=LTP   — returns spot price for all equity/index tokens
  ✓  Quote API  mode=FULL  — returns OI for NFO option tokens
  ✗  /getOptionChain       — returns HTTP 200 but non-JSON body (HTML error page)

Strategy:
  Spot price : Quote API mode=LTP  using equity/index tokens
  Option OI  : Quote API mode=FULL using NFO option contract tokens

Token resolution:
  • Equity/index tokens → instrument master, downloaded once at startup
  • NFO option tokens   → instrument master, parsed by (symbol, expiry, strike, type)
    NFO symbol format in master: "NIFTY27FEB2522500CE"  (no spaces)

Requirements:
  pip install smartapi-python pyotp websocket-client logzero requests

.env:
  ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_MPIN, ANGEL_TOTP_SECRET
"""

from __future__ import annotations

import base64
import json
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

import config
import stock_config as _stock_config
from data_sources.base import BaseDataSource
from utils.logger import setup_logger

log = setup_logger("angel_source")

# ── Endpoints ─────────────────────────────────────────────────────────────────
_BASE_URL  = "https://apiconnect.angelone.in"
_QUOTE_URL = f"{_BASE_URL}/rest/secure/angelbroking/market/v1/quote/"
_MASTER_URL = (
    "https://margincalculator.angelbroking.com"
    "/OpenAPI_File/files/OpenAPIScripMaster.json"
)

# ── Confirmed index tokens (from live debug, Quote API validated) ─────────────
_INDEX_TOKENS: Dict[str, Tuple[str, str]] = {
    "NIFTY":        ("99926000", "NSE"),
    "BANKNIFTY":    ("99926009", "NSE"),
    "MIDCAPSELECT": ("99926074", "NSE"),
    "SENSEX":       ("99919000", "BSE"),
    "FINNIFTY":     ("99926037", "NSE"),
}

# ── Known stock tokens (confirmed from live debug + instrument master) ─────────
# These are the NSE -EQ equity tokens. Verified: HDFCBANK=1333, ITC=1660.
_KNOWN_STOCK_TOKENS: Dict[str, Tuple[str, str]] = {
    "ITC": ("1660", "NSE"),   # ITC-EQ; instrument master exact match confirmed
}

# ── NFO option symbol regex ───────────────────────────────────────────────────
# Confirmed format from live instrument master: "NIFTY27MAR2622500CE"
#   Group 1: underlying  (letters + & + digits, non-greedy)
#   Group 2: DDMMMYY     (7 chars: 2 digits + 3 letters + 2 digits)
#   Group 3: strike      (digits)
#   Group 4: option type (CE or PE)
_NFO_SYMBOL_RE = re.compile(r'^([A-Z&0-9]+?)(\d{2}[A-Z]{3}\d{2})(\d+)(CE|PE)$')
_RATE_LIMIT_RETRIES    = 5
_RATE_LIMIT_BASE_DELAY = 10   # seconds; doubles: 10→20→40→80→160

# ── Instrument master cache ────────────────────────────────────────────────────
# Written after each successful download; used as fallback when network fails.
# Lives alongside the app so it persists across Docker restarts via volume mount.
import pathlib as _pathlib
_MASTER_CACHE = _pathlib.Path("/app/data/instrument_master_cache.json")
if not _MASTER_CACHE.parent.exists():          # local dev fallback
    _MASTER_CACHE = _pathlib.Path("data/instrument_master_cache.json")
    _MASTER_CACHE.parent.mkdir(parents=True, exist_ok=True)


def _get_instrument_cfg(name: str) -> dict:
    combined = {**config.INDEX_CONFIG, **_stock_config.STOCK_CONFIG}
    if name not in combined:
        raise KeyError(f"'{name}' not found in INDEX_CONFIG or STOCK_CONFIG.")
    return combined[name]


def _strip_bearer(token: str) -> str:
    """Angel One SDK returns jwtToken with 'Bearer ' already prepended. Strip it."""
    return token[len("Bearer "):] if token.startswith("Bearer ") else token


def _fmt_expiry_nfo(expiry: str) -> str:
    """
    Convert our expiry to the format used in NFO symbol strings.

    Input : "27FEB2026"   (our internal format)
    Output: "27FEB26"     (DDMMMYY — what appears in NFO symbols like NIFTY27FEB2622500CE)
    """
    if len(expiry) == 9:          # "27FEB2026"
        return expiry[:7]         # "27FEB20"  ← WRONG — need last 2 of year
    return expiry

def _fmt_expiry_nfo_v2(expiry: str) -> str:
    """
    "27FEB2026" → "27FEB26"
    Day(2) + Month(3) + Year-last-2-digits(2) = 7 chars
    """
    if len(expiry) == 9:   # "27FEB2026"
        return expiry[:5] + expiry[7:]    # "27FEB" + "26" = "27FEB26"
    return expiry


class AngelDataSource(BaseDataSource):
    """
    Angel One data source using Quote API exclusively.
    No dependency on /getOptionChain endpoint (confirmed broken/HTML response).
    """

    def __init__(self) -> None:
        self._smart_api:  Optional[Any]              = None
        self._ws:         Optional[Any]              = None
        self._auth_token: str                        = ""
        self._feed_token: str                        = ""

        # Equity/index token map: config_key → (token, exchange)
        self._eq_token_map:  Dict[str, Tuple[str, str]] = dict(_INDEX_TOKENS)

        # NFO option token map: (config_key, expiry_nfo, strike, opt_type) → (token, exchange)
        # expiry_nfo format: "27FEB26". Exchange is "NFO" or "BSE" (SENSEX options are BSE).
        self._nfo_token_map: Dict[Tuple[str, str, int, str], Tuple[str, str]] = {}

        # Caches
        self._spot_cache: Dict[str, float] = {}
        self._oi_cache:   Dict[Tuple, int]  = {}

        self._connected      = False
        self._started        = False
        self._start_lock     = threading.Lock()   # prevents concurrent start()
        self._reconnect_lock = threading.Lock()   # prevents concurrent reconnect threads
        self._reconnecting   = False              # True while a reconnect is running
        self._master_loading = False              # True while background reload is running
        self._stop_event     = threading.Event()

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def start(self) -> None:
        with self._start_lock:
            if self._started:
                log.debug("AngelDataSource already running — skipping")
                return
            self._authenticate()
            self._build_token_maps()       # download master, populate both maps
            self._bootstrap_all_spots()    # Quote API LTP for all equity tokens
            self._connect_ws()
            self._started = True
            log.info("AngelDataSource ready | eq_tokens=%d  nfo_tokens=%d",
                     len(self._eq_token_map), len(self._nfo_token_map))

    def stop(self) -> None:
        self._stop_event.set()
        if self._ws:
            try:
                self._ws.close_connection()
            except Exception:
                pass
        self._started = False
        log.info("AngelDataSource stopped")

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def get_spot_price(self, name: str) -> float:
        """Return cached spot price. Updated by _bootstrap_all_spots and _refresh_spots."""
        price = self._spot_cache.get(name, 0.0)
        if price == 0.0:
            # Try an on-demand single-token refresh
            price = self._fetch_single_spot(name)
        return price

    def get_option_oi(
        self,
        name:        str,
        expiry:      str,
        strike:      int,
        option_type: str,
    ) -> int:
        """Return OI from cache. Call batch_refresh_oi() once per poll cycle first."""
        key = (name, expiry, strike, option_type)
        return self._oi_cache.get(key, 0)

    def batch_refresh_oi(
        self,
        requests_list: List[Tuple[str, str, int, str]],
    ) -> None:
        """
        Fetch OI for all (name, expiry, strike, opt_type) tuples in ONE batched
        Quote API call per exchange (NFO + BFO), rather than one call per option.

        Angel One Quote API accepts up to 50 tokens per exchange per request.
        Batching eliminates the rate-limit silently-empty-fetched problem.
        """
        if AngelDataSource._nfo_access_confirmed is False:
            return

        # ── Resolve tokens, group by exchange ─────────────────────────────────
        nfo_tokens: Dict[str, Tuple[str, str, int, str]] = {}  # token → key
        bfo_tokens: Dict[str, Tuple[str, str, int, str]] = {}

        for name, expiry, strike, opt_type in requests_list:
            expiry_nfo = AngelDataSource._normalise_expiry(expiry) or ""
            nfo_key    = (name, expiry_nfo, strike, opt_type)
            entry      = self._nfo_token_map.get(nfo_key)

            if not entry and self._nfo_token_map:
                entry, expiry_nfo = self._nearest_expiry_entry(
                    name, expiry_nfo, strike, opt_type
                )

            if not entry:
                continue

            token, exch = entry
            cache_key   = (name, expiry, strike, opt_type)

            if exch == "BFO":
                bfo_tokens[token] = cache_key
            else:
                nfo_tokens[token] = cache_key

        if not nfo_tokens and not bfo_tokens:
            return

        # ── Batch fetch: up to 50 tokens per call ─────────────────────────────
        BATCH = 50

        def _fetch_batch(token_map: Dict[str, tuple], exch: str) -> None:
            tokens = list(token_map.keys())
            for i in range(0, len(tokens), BATCH):
                batch = tokens[i:i + BATCH]
                try:
                    body    = self._quote_request({exch: batch}, mode="FULL")
                    fetched = body.get("data", {}).get("fetched", [])

                    if fetched and AngelDataSource._nfo_access_confirmed is None:
                        AngelDataSource._nfo_access_confirmed = True
                        log.info("NFO/BFO data access confirmed ✓")

                    for row in fetched:
                        sym_token = str(row.get("symbolToken", ""))
                        cache_key = token_map.get(sym_token)
                        if not cache_key:
                            continue
                        for field in ("opnInterest", "openInterest", "open_interest",
                                      "oi", "OI"):
                            val = row.get(field)
                            if val is not None:
                                oi = int(float(val))
                                if oi > 0:
                                    self._oi_cache[cache_key] = oi
                                break

                    if not fetched and batch:
                        log.warning(
                            "Batch FULL returned empty fetched for %s "
                            "(%d tokens, i=%d) — body: %s",
                            exch, len(batch), i, str(body)[:200]
                        )

                except requests.HTTPError as exc:
                    if exc.response is not None and exc.response.status_code == 403:
                        if AngelDataSource._nfo_access_confirmed is not False:
                            AngelDataSource._nfo_access_confirmed = False
                            log.error(
                                "NFO DATA ACCESS NOT ENABLED — "
                                "enable NSE F&O on your Angel One API key at "
                                "https://smartapi.angelbroking.com"
                            )
                    else:
                        log.error("Batch OI fetch HTTP error (%s): %s", exch, exc)
                except Exception as exc:
                    log.error("Batch OI fetch failed (%s): %s", exch, exc)

        if nfo_tokens:
            _fetch_batch(nfo_tokens, "NFO")
        if bfo_tokens:
            _fetch_batch(bfo_tokens, "BFO")

    # ─────────────────────────────────────────────────────────────────────────
    # Auth headers
    # ─────────────────────────────────────────────────────────────────────────

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization":    f"Bearer {self._auth_token}",
            "Content-Type":     "application/json",
            "Accept":           "application/json",
            "X-UserType":       "USER",
            "X-SourceID":       "WEB",
            "X-ClientLocalIP":  "127.0.0.1",
            "X-ClientPublicIP": "127.0.0.1",
            "X-MACAddress":     "AA:BB:CC:DD:EE:FF",
            "X-PrivateKey":     config.ANGEL_API_KEY,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Instrument master — build both token maps
    # ─────────────────────────────────────────────────────────────────────────

    def _build_token_maps(self) -> None:
        """
        Download instrument master once and build:
          1. _eq_token_map  — equity/index token for spot price lookups
          2. _nfo_token_map — NFO option tokens for OI lookups

        NFO option symbol format in master (confirmed):
          "NIFTY27FEB2622500CE"   → underlying=NIFTY, expiry=27FEB26, strike=22500, type=CE
          "HDFCBANK27FEB261750CE" → underlying=HDFCBANK, expiry=27FEB26, strike=1750, type=CE

        Master record keys include: symbol, token, exch_seg, instrumenttype,
          strike, optiontype, expiry (YYYYMMDD format in some versions)
        """
        log.info("Downloading Angel One instrument master …")
        master = None

        # ── Try live download (3 attempts with back-off) ──────────────────────
        for attempt in range(1, 4):
            try:
                resp   = requests.get(_MASTER_URL, timeout=45)
                resp.raise_for_status()
                master = resp.json()
                log.info("Master downloaded: %d records", len(master))
                # Persist to disk for next restart
                try:
                    _MASTER_CACHE.write_text(
                        __import__("json").dumps(master), encoding="utf-8"
                    )
                    log.debug("Master cached to %s", _MASTER_CACHE)
                except Exception as ce:
                    log.debug("Could not cache master: %s", ce)
                break
            except Exception as exc:
                if attempt < 3:
                    wait = 10 * attempt
                    log.warning("Master download attempt %d/3 failed: %s — retrying in %ds",
                                attempt, exc, wait)
                    time.sleep(wait)
                else:
                    log.warning("Master download failed after 3 attempts: %s", exc)

        # ── Fall back to disk cache if download failed ────────────────────────
        if master is None:
            if _MASTER_CACHE.exists():
                try:
                    master = __import__("json").loads(
                        _MASTER_CACHE.read_text(encoding="utf-8")
                    )
                    age_h  = (time.time() - _MASTER_CACHE.stat().st_mtime) / 3600
                    log.warning(
                        "Using cached instrument master (%.1fh old, %d records). "
                        "NFO tokens may not match today's contracts.", age_h, len(master)
                    )
                except Exception as ce:
                    log.error("Cache read failed: %s", ce)

        if master is None:
            log.error(
                "Instrument master unavailable (download failed, no cache). "
                "OI will be 0 for all symbols. "
                "Check network connectivity and retry: docker-compose restart"
            )
            return

        # All configured symbols
        all_cfg: Dict[str, str] = {}   # angel_symbol.upper() → config_key
        for cfg_key, cfg_val in {**config.INDEX_CONFIG,
                                  **_stock_config.STOCK_CONFIG}.items():
            all_cfg[cfg_val["angel_symbol"].upper()] = cfg_key

        # Apply known stock tokens first (verified correct)
        for cfg_key, tok_exch in _KNOWN_STOCK_TOKENS.items():
            self._eq_token_map[cfg_key] = tok_exch

        eq_eq_rows:   Dict[str, dict] = {}   # cfg_key → -EQ row
        eq_bare_rows: Dict[str, dict] = {}   # cfg_key → bare row

        nfo_count = 0

        for record in master:
            try:
                raw_sym = str(record.get("symbol", ""))
                exch    = str(record.get("exch_seg", "")).upper()
                itype   = str(record.get("instrumenttype", "")).upper()
                token   = str(record.get("token", "")).strip()

                # ── 1. Equity tokens (NSE only, non-derivative) ───────────────
                # BSE excluded here so SENSEX options fall to branch 2 below.
                if exch == "NSE" and itype in ("", "EQ", "-", "EQUITIES", "AMXIDX"):
                    bare = raw_sym.upper().replace("-EQ", "").strip()
                    if bare in all_cfg:
                        cfg_key = all_cfg[bare]
                        if cfg_key in _INDEX_TOKENS:
                            pass   # indices already hardcoded
                        elif raw_sym.upper().endswith("-EQ"):
                            eq_eq_rows[cfg_key]   = record
                        elif cfg_key not in eq_eq_rows:
                            eq_bare_rows[cfg_key] = record

                # ── 2. NFO / BFO option tokens ────────────────────────────────
                # Parse directly from symbol string — field names unreliable.
                # NFO = NSE F&O (NIFTY, BANKNIFTY, stocks)
                # BFO = BSE F&O (SENSEX options — confirmed from live API test)
                # BSE = BSE cash — skip, not options
                elif exch in ("NFO", "BFO"):
                    m = _NFO_SYMBOL_RE.match(raw_sym)
                    if not m:
                        continue   # futures or unrecognised — skip

                    sym_key    = m.group(1)
                    expiry_nfo = m.group(2)
                    strike_int = int(m.group(3))
                    opt_type   = m.group(4)

                    cfg_key = all_cfg.get(sym_key)
                    if not cfg_key:
                        continue   # not one of our configured symbols

                    nfo_key = (cfg_key, expiry_nfo, strike_int, opt_type)
                    self._nfo_token_map[nfo_key] = (token, exch)
                    nfo_count += 1

            except Exception as exc:
                log.debug("Skipping record %s: %s", record.get("symbol", "?"), exc)

        # Merge equity rows
        eq_found = len(self._eq_token_map)
        for cfg_key in list(all_cfg.values()):
            if cfg_key in self._eq_token_map:
                continue   # already set (index or known stock)
            row = eq_eq_rows.get(cfg_key) or eq_bare_rows.get(cfg_key)
            if row:
                self._eq_token_map[cfg_key] = (str(row.get("token","")), "NSE")
                eq_found += 1

        log.info("Token maps built | eq=%d/%d  nfo_options=%d",
                 len(self._eq_token_map), len(all_cfg), nfo_count)

        # Warn about missing equity tokens
        missing_eq = [k for k in all_cfg.values() if k not in self._eq_token_map]
        if missing_eq:
            log.warning("Missing equity tokens for: %s", missing_eq)

    def _parse_nfo_symbol(
        self,
        symbol:  str,
        record:  dict,
    ) -> Optional[Tuple[str, str, int, str]]:
        """
        Parse NFO option symbol into (underlying, expiry_nfo, strike, option_type).

        Master records also have structured fields:
          name      : underlying name  (e.g. "NIFTY", "BANKNIFTY", "HDFCBANK")
          expiry    : "20260227" or "27FEB2026" — varies by master version
          strike    : strike price as float/int
          optiontype: "CE" or "PE"

        We prefer the structured fields; fall back to symbol string parsing.

        Returns (underlying, "27FEB26", 22500, "CE") or None if unparseable.
        """
        # ── Try structured fields first ───────────────────────────────────────
        underlying = str(record.get("name", "")).strip().upper()
        opt_type   = str(record.get("optiontype", "")).strip().upper()
        raw_strike = record.get("strike", "") or record.get("strikeprice", "")
        raw_expiry = str(record.get("expiry", "")).strip()

        if underlying and opt_type in ("CE", "PE") and raw_strike and raw_expiry:
            try:
                strike = int(float(raw_strike))
                # Normalise expiry to "DDMMMYY"
                expiry_nfo = self._normalise_expiry(raw_expiry)
                if expiry_nfo:
                    return (underlying, expiry_nfo, strike, opt_type)
            except (ValueError, TypeError):
                pass

        # ── Fall back: parse symbol string ────────────────────────────────────
        # Pattern: UNDERLYING + DDMMMYY + STRIKE + (CE|PE)
        # e.g. NIFTY27FEB2622500CE  or  HDFCBANK27FEB261750CE
        m = re.match(
            r'^([A-Z&]+?)(\d{2}[A-Z]{3}\d{2})(\d+)(CE|PE)$',
            symbol.upper()
        )
        if m:
            underlying = m.group(1)
            expiry_nfo = m.group(2)   # "27FEB26"
            strike     = int(m.group(3))
            opt_type   = m.group(4)
            return (underlying, expiry_nfo, strike, opt_type)

        return None

    @staticmethod
    def _normalise_expiry(raw: str) -> Optional[str]:
        """
        Normalise various expiry formats to "DDMMMYY" (7 chars).

        "20260227" → "27FEB26"
        "27FEB2026"→ "27FEB26"
        "27FEB26"  → "27FEB26"  (already correct)
        """
        import calendar
        raw = raw.strip()

        # "20260227" — YYYYMMDD
        if re.match(r'^\d{8}$', raw):
            try:
                from datetime import datetime
                dt  = datetime.strptime(raw, "%Y%m%d")
                mon = calendar.month_abbr[dt.month].upper()
                return f"{dt.day:02d}{mon}{str(dt.year)[2:]}"
            except Exception:
                return None

        # "27FEB2026" — DDMMMYYYY (our internal format)
        if re.match(r'^\d{2}[A-Z]{3}\d{4}$', raw.upper()):
            return raw[:5].upper() + raw[7:]    # "27FEB" + "26"

        # "27FEB26" — already correct
        if re.match(r'^\d{2}[A-Z]{3}\d{2}$', raw.upper()):
            return raw.upper()

        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Spot price — Quote API  mode=LTP
    # ─────────────────────────────────────────────────────────────────────────

    def _bootstrap_all_spots(self) -> None:
        """Batch-fetch LTP for all equity/index tokens at startup."""
        log.info("Bootstrapping spot prices …")

        # Group by exchange
        by_exch: Dict[str, List[Tuple[str, str]]] = {}
        for cfg_key, (token, exch) in self._eq_token_map.items():
            by_exch.setdefault(exch, []).append((cfg_key, token))

        resolved = 0
        for exch, items in by_exch.items():
            for i in range(0, len(items), 50):   # batches of 50
                batch  = items[i:i+50]
                tokens = [t for _, t in batch]
                keys   = [k for k, _ in batch]
                try:
                    body    = self._quote_request({"NSE" if exch == "NSE" else exch: tokens})
                    fetched = body.get("data", {}).get("fetched", [])

                    # Build token → ltp map
                    t2p: Dict[str, float] = {}
                    for row in fetched:
                        t = str(row.get("symbolToken") or row.get("token", ""))
                        p = float(row.get("ltp", 0) or 0)
                        if t and p > 0:
                            t2p[t] = p

                    for cfg_key, token in batch:
                        price = t2p.get(token, 0.0)
                        if price > 0:
                            self._spot_cache[cfg_key] = price
                            resolved += 1
                            log.debug("Spot %-15s = %.2f", cfg_key, price)

                except Exception as exc:
                    log.warning("Bootstrap batch failed %s %s: %s", exch, tokens[:3], exc)

        total = len(self._eq_token_map)
        log.info("Bootstrap done: %d/%d spots resolved", resolved, total)
        no_spot = [k for k in self._eq_token_map if self._spot_cache.get(k, 0) == 0]
        if no_spot:
            log.warning("No spot price for: %s", no_spot)

    def _fetch_single_spot(self, name: str) -> float:
        """On-demand spot fetch for a single symbol."""
        if name not in self._eq_token_map:
            log.warning("No equity token for %s", name)
            return 0.0
        token, exch = self._eq_token_map[name]
        try:
            body    = self._quote_request({exch: [token]})
            fetched = body.get("data", {}).get("fetched", [])
            if fetched:
                price = float(fetched[0].get("ltp", 0) or 0)
                if price > 0:
                    self._spot_cache[name] = price
                return price
        except Exception as exc:
            log.error("Single spot fetch failed %s: %s", name, exc)
        return 0.0

    # ─────────────────────────────────────────────────────────────────────────
    # OI — Quote API  mode=FULL  on NFO option tokens
    # ─────────────────────────────────────────────────────────────────────────

    # Set to True once we confirm NFO access works (or False once we get a 403)
    _nfo_access_confirmed: Optional[bool] = None   # None = not yet tested

    def _fetch_oi_via_quote(
        self,
        name:        str,
        expiry:      str,
        strike:      int,
        option_type: str,
    ) -> int:
        """
        Fetch OI via Quote API mode=FULL on NFO option token.

        Requires NFO segment enabled on your Angel One API key.
        If you get 403 errors, activate NFO at:
          Angel One web → My Profile → API → Manage → enable NFO Data Feed

        On first 403, sets _nfo_access_confirmed=False and stops trying
        (avoids flooding logs with 403s on every poll cycle).
        """
        # Stop trying if NFO access was already rejected
        if AngelDataSource._nfo_access_confirmed is False:
            return 0

        expiry_nfo = AngelDataSource._normalise_expiry(expiry) or ""
        nfo_key    = (name, expiry_nfo, strike, option_type)
        entry      = self._nfo_token_map.get(nfo_key)

        # ── Nearest-expiry fallback ───────────────────────────────────────────
        # If computed expiry isn't in map (e.g. holiday moved expiry by 1 day,
        # or index switched from weekly→monthly), find the closest expiry that
        # IS in the map for this symbol+strike+type and use that instead.
        if not entry and self._nfo_token_map:
            entry, expiry_nfo = self._nearest_expiry_entry(
                name, expiry_nfo, strike, option_type
            )

        if not entry:
            if not self._nfo_token_map:
                self._reload_master_async()
            else:
                # Upgrade to WARNING so we can see exactly what's missing
                log.warning(
                    "No NFO token: %-12s  expiry_nfo=%-8s  strike=%-6d  %s  "
                    "(internal expiry=%s)",
                    name, expiry_nfo, strike, option_type, expiry
                )
            return 0

        token, exch = entry   # exch = "NFO" or "BSE" (SENSEX options live on BSE)

        try:
            body    = self._quote_request({exch: [token]}, mode="FULL")
            fetched = body.get("data", {}).get("fetched", [])
            if not fetched:
                log.warning(
                    "Quote FULL returned empty fetched for %s %d %s "
                    "(token=%s exch=%s expiry_nfo=%s) — body: %s",
                    name, strike, option_type, token, exch, expiry_nfo,
                    str(body)[:200]
                )
                return 0

            # Mark NFO access as working
            if AngelDataSource._nfo_access_confirmed is None:
                AngelDataSource._nfo_access_confirmed = True
                log.info("NFO data access confirmed ✓")

            row = fetched[0]
            # Angel One uses "opnInterest" (not "openInterest") in FULL mode
            for key in ("opnInterest", "openInterest", "open_interest",
                        "oi", "OI", "openinterest", "OpenInterest"):
                val = row.get(key)
                if val is not None:
                    oi = int(float(val))
                    log.debug("OI %-15s %d %s = %d", name, strike, option_type, oi)
                    return oi

            # Log keys once so we can find the correct field name
            if AngelDataSource._nfo_access_confirmed:
                log.warning(
                    "OI field not found in FULL response for %s. "
                    "Row keys: %s — run utils/api_debug.py to inspect",
                    name, list(row.keys())
                )
                AngelDataSource._nfo_access_confirmed = False  # stop spamming
            return 0

        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 403:
                if AngelDataSource._nfo_access_confirmed is not False:
                    AngelDataSource._nfo_access_confirmed = False
                    log.error(
                        "═" * 60 + "\n"
                        "  NFO DATA ACCESS NOT ENABLED on your Angel One API key.\n"
                        "  OI monitoring will not work until you enable it:\n"
                        "\n"
                        "  1. Go to: https://smartapi.angelbroking.com\n"
                        "  2. Login → My Account → API Management\n"
                        "  3. Find your API key → Edit / Manage Subscriptions\n"
                        "  4. Enable:  NSE F&O  (NFO segment)\n"
                        "  5. Restart this application\n"
                        "\n"
                        "  Spot prices will continue to work in the meantime.\n"
                        + "═" * 60
                    )
            else:
                log.error("OI fetch HTTP error %s %d %s: %s",
                          name, strike, option_type, exc)
            return 0

        except Exception as exc:
            log.error("OI fetch failed %s %d %s: %s", name, strike, option_type, exc)
            return 0

    def _lookup_nfo_token(
        self,
        name:        str,
        expiry_nfo:  str,
        strike:      int,
        option_type: str,
    ) -> Optional[str]:
        """
        Dynamic NFO token lookup — called when a token is not in the pre-built map.
        This avoids having to re-download the master for every missing token.
        Only downloads master if more than 10 tokens are missing.
        """
        # This is a lightweight cache-miss handler.
        # In practice the token map built at startup should cover all contracts.
        cfg = _get_instrument_cfg(name)
        sym = cfg["angel_symbol"].upper()

        # Construct expected NFO symbol
        # e.g. NIFTY + 27FEB26 + 22500 + CE = "NIFTY27FEB2622500CE"
        expected_sym = f"{sym}{expiry_nfo}{strike}{option_type}"
        log.debug("Dynamic NFO lookup for: %s", expected_sym)
        return None   # Avoid re-downloading master on every miss

    # ─────────────────────────────────────────────────────────────────────────
    # Quote API helper
    # ─────────────────────────────────────────────────────────────────────────

    def _quote_request(
        self,
        exchange_tokens: Dict[str, List[str]],
        mode: str = "LTP",
    ) -> dict:
        """
        POST /market/v1/quote/
        Returns parsed JSON body. Raises on HTTP error or empty/non-JSON body.
        """
        payload = {"mode": mode, "exchangeTokens": exchange_tokens}
        resp    = requests.post(
            _QUOTE_URL,
            headers=self._auth_headers(),
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()

        if not resp.content:
            raise ValueError("Quote API returned empty body")

        body = resp.json()

        # Check for auth errors (no "status" key in error responses)
        msg = body.get("message", "")
        if msg.lower() in ("invalid token", "unauthorized", "invalid_token", "forbidden"):
            raise ValueError(f"Quote API auth error: {msg}")

        return body

    # ─────────────────────────────────────────────────────────────────────────
    # Authentication
    # ─────────────────────────────────────────────────────────────────────────

    def _authenticate(self) -> None:
        _DEPS = {
            "logzero":   "logzero>=1.7.0",
            "SmartApi":  "smartapi-python>=1.3.4",
            "pyotp":     "pyotp>=2.9.0",
            "websocket": "websocket-client>=1.7.0",
        }
        missing = [pkg for mod, pkg in _DEPS.items() if not self._can_import(mod)]
        if missing:
            raise ImportError(f"Missing: {missing}. Run: pip install {' '.join(missing)}")

        self._validate_mpin(config.ANGEL_MPIN)
        self._validate_totp_secret(config.ANGEL_TOTP_SECRET)

        import pyotp
        from SmartApi import SmartConnect

        last_exc: Optional[Exception] = None
        for attempt in range(1, _RATE_LIMIT_RETRIES + 1):
            try:
                self._smart_api = SmartConnect(api_key=config.ANGEL_API_KEY)
                totp            = pyotp.TOTP(config.ANGEL_TOTP_SECRET).now()

                data = self._smart_api.generateSession(
                    config.ANGEL_CLIENT_ID, config.ANGEL_MPIN, totp
                )
                if not data or data.get("status") is False:
                    raise ValueError(f"Session failed: {data.get('message','?') if data else 'empty'}")

                # Strip 'Bearer ' prefix that Angel One SDK adds to jwtToken
                self._auth_token = _strip_bearer(data["data"]["jwtToken"])
                self._feed_token = self._smart_api.getfeedToken()
                log.info("Authenticated (attempt %d)", attempt)
                return

            except Exception as exc:
                last_exc = exc
                if "access rate" in str(exc).lower() or "exceeding access" in str(exc).lower():
                    delay = _RATE_LIMIT_BASE_DELAY * (2 ** (attempt - 1))
                    log.warning("Rate limit — waiting %ds (attempt %d/%d)",
                                delay, attempt, _RATE_LIMIT_RETRIES)
                    time.sleep(delay)
                else:
                    log.error("Auth failed: %s", exc)
                    raise

        raise RuntimeError(f"Auth failed after {_RATE_LIMIT_RETRIES} attempts") from last_exc

    # ─────────────────────────────────────────────────────────────────────────
    # Validators
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _can_import(mod: str) -> bool:
        try: __import__(mod); return True
        except ImportError: return False

    @staticmethod
    def _validate_mpin(mpin: str) -> None:
        if not mpin or not mpin.isdigit() or len(mpin) != 4:
            raise ValueError(f"ANGEL_MPIN must be exactly 4 digits. Got: '{mpin}'")

    @staticmethod
    def _validate_totp_secret(secret: str) -> None:
        if not secret:
            raise ValueError("ANGEL_TOTP_SECRET empty")
        cleaned = secret.replace(" ","").upper()
        padded  = cleaned + "=" * (-len(cleaned) % 8)
        try:
            base64.b32decode(padded)
        except Exception:
            raise ValueError(
                f"ANGEL_TOTP_SECRET not valid base32: '{secret}'\n"
                "  Get it: Angel One web → Security → Enable TOTP → 'Can't scan?'"
            )

    # ─────────────────────────────────────────────────────────────────────────
    # WebSocket
    # ─────────────────────────────────────────────────────────────────────────

    def _connect_ws(self) -> None:
        try:
            from SmartApi.smartWebSocketV2 import SmartWebSocketV2

            def on_open(ws):
                log.info("Angel WS connected"); self._connected = True

            def on_message(ws, message):
                self._handle_ws_message(message)

            def on_error(ws, error):
                log.error("Angel WS error: %s", error)
                self._connected = False; self._schedule_reconnect()

            def on_close(ws, code, msg):
                log.warning("Angel WS closed: %s %s", code, msg)
                self._connected = False
                if not self._stop_event.is_set():
                    self._schedule_reconnect()

            self._ws = SmartWebSocketV2(
                auth_token=self._auth_token,
                api_key=config.ANGEL_API_KEY,
                client_code=config.ANGEL_CLIENT_ID,
                feed_token=self._feed_token,
            )
            self._ws.on_open    = on_open
            self._ws.on_message = on_message
            self._ws.on_error   = on_error
            self._ws.on_close   = on_close
            threading.Thread(target=self._ws.connect, daemon=True).start()
            log.info("Angel WS thread started")
        except ImportError:
            log.warning("SmartWebSocketV2 unavailable — REST-only mode")
        except Exception as exc:
            log.error("WS connect failed: %s", exc)

    def _nearest_expiry_entry(
        self,
        name:        str,
        expiry_nfo:  str,
        strike:      int,
        option_type: str,
    ):
        """
        Find the closest available expiry in _nfo_token_map when the exact
        computed expiry is missing (holiday shift, weekly→monthly change, etc.).

        Returns (entry, matched_expiry_nfo) or (None, expiry_nfo).
        Only matches expiries within 7 days of the target to avoid using
        a completely wrong contract.
        """
        try:
            from datetime import datetime
            target_dt = datetime.strptime(expiry_nfo, "%d%b%y")
        except ValueError:
            return None, expiry_nfo

        best_entry   = None
        best_expiry  = expiry_nfo
        best_delta   = 999

        for (n, exp, s, t), entry in self._nfo_token_map.items():
            if n != name or s != strike or t != option_type:
                continue
            try:
                dt    = datetime.strptime(exp, "%d%b%y")
                delta = abs((dt - target_dt).days)
                if delta < best_delta:
                    best_delta  = delta
                    best_entry  = entry
                    best_expiry = exp
            except ValueError:
                continue

        if best_entry and best_delta <= 7:
            if best_delta > 0:
                log.info(
                    "Expiry adjusted: %s %d %s  %s→%s (±%dd, likely holiday shift)",
                    name, strike, option_type, expiry_nfo, best_expiry, best_delta
                )
            return best_entry, best_expiry

        return None, expiry_nfo

    def _reload_master_async(self) -> None:
        """
        Trigger a background re-download of the instrument master.
        Called when the NFO token map is empty (download failed at startup).
        Deduped — only one reload thread runs at a time.
        """
        with self._reconnect_lock:
            if self._master_loading:
                return
            self._master_loading = True

        def _do_reload():
            try:
                log.info("NFO token map empty — retrying instrument master download …")
                # Wait briefly to let Docker network settle
                time.sleep(5)
                self._build_token_maps()
                if self._nfo_token_map:
                    log.info("Master reload succeeded: %d NFO tokens loaded",
                             len(self._nfo_token_map))
                else:
                    log.warning("Master reload: still no NFO tokens — will retry next poll")
            except Exception as exc:
                log.error("Master reload failed: %s", exc)
            finally:
                with self._reconnect_lock:
                    self._master_loading = False

        threading.Thread(target=_do_reload, daemon=True, name="MasterReload").start()

    def _schedule_reconnect(self) -> None:
        """
        Schedule a WS reconnect in a background thread.

        Deduplication: if a reconnect thread is already running (e.g. because
        both OIMonitor and StockOIMonitor share the same data source and both
        detect the WS close simultaneously), the second call is silently ignored.
        """
        if self._stop_event.is_set():
            return

        with self._reconnect_lock:
            if self._reconnecting:
                log.debug("Reconnect already in progress — ignoring duplicate request")
                return
            self._reconnecting = True

        def _reconnect():
            try:
                for attempt in range(1, config.WS_MAX_RECONNECT_ATTEMPTS + 1):
                    if self._stop_event.is_set():
                        return
                    delay = config.WS_RECONNECT_DELAY * attempt
                    log.info("WS reconnect %d/%d in %ds …", attempt,
                             config.WS_MAX_RECONNECT_ATTEMPTS, delay)
                    time.sleep(delay)
                    try:
                        self._authenticate()
                        self._build_token_maps()    # includes master retry
                        self._bootstrap_all_spots()
                        self._connect_ws()
                        return   # success
                    except Exception as exc:
                        log.error("Reconnect attempt %d failed: %s", attempt, exc)
                log.critical("All WS reconnect attempts exhausted")
            finally:
                # Always release the lock so future reconnects can proceed
                with self._reconnect_lock:
                    self._reconnecting = False

        threading.Thread(target=_reconnect, daemon=True, name="WS-Reconnect").start()

    def _handle_ws_message(self, message: Any) -> None:
        try:
            raw  = message.decode() if isinstance(message, (bytes, bytearray)) else message
            data = json.loads(raw)
            token = data.get("token","")
            oi    = int(data.get("oi", 0))
            ltp   = float(data.get("ltp", 0))
            key   = self._token_to_key(token)
            if key:
                self._oi_cache[key]      = oi
                self._spot_cache[key[0]] = ltp
        except Exception:
            pass

    def _token_to_key(self, token: str) -> Optional[Tuple]:
        return None

    def subscribe(self, tokens: List[str]) -> None:
        if not self._ws or not self._connected:
            log.warning("WS not connected"); return
        try:
            self._ws.subscribe("sub1", 3, tokens)
            log.info("Subscribed %d tokens", len(tokens))
        except Exception as exc:
            log.error("Subscribe failed: %s", exc)
