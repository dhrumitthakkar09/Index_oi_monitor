"""
utils/nse_prev_oi.py — Fetch previous day's OI from NSE India option chain API.

NSE option chain includes:
  openInterest         = today's current OI
  changeinOpenInterest = change vs previous day
  → prev_day_oi = openInterest - changeinOpenInterest

API endpoints:
  Indices: https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY
  Stocks:  https://www.nseindia.com/api/option-chain-equities?symbol=HDFCBANK

NSE requires a valid browser session (cookies set by visiting homepage first).
Data is fetched ONCE per day at startup and cached in memory.
SENSEX is on BSE — not available via NSE API; falls back to None.
"""

from __future__ import annotations

import time
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple

from utils.logger import setup_logger

log = setup_logger("nse_prev_oi")

IST = timezone(timedelta(hours=5, minutes=30))

# NSE indices that use the "indices" endpoint (vs "equities")
_NSE_INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "MIDCPNIFTY", "FINNIFTY", "NIFTYNXT50"}

# Angel symbol → NSE option chain symbol (where they differ)
_SYMBOL_MAP = {
    "MIDCPNIFTY": "NIFTY MIDCAP SELECT",   # NSE uses full name
    "BANKNIFTY":  "BANKNIFTY",
    "NIFTY":      "NIFTY",
}

# Cache: {(angel_symbol, expiry_str, strike, opt_type): prev_day_oi}
# expiry_str is in "25MAR26" format (same as rest of app)
_cache: Dict[Tuple[str, str, int, str], int] = {}
_cache_date: Optional[str] = None        # "YYYY-MM-DD" when cache was last populated
_cache_lock  = threading.Lock()


def get_prev_day_oi(angel_symbol: str, expiry_str: str, strike: int, opt_type: str) -> int:
    """
    Return previous day's OI for this option.
    Returns 0 if unavailable (SENSEX/BFO, first run, or NSE fetch failed).
    """
    with _cache_lock:
        key = (angel_symbol, expiry_str, strike, opt_type)
        return _cache.get(key, 0)


def refresh_if_needed(angel_symbols: list[str]) -> None:
    """
    Called once at startup (and daily).
    Fetches NSE option chain for all relevant symbols and populates _cache.
    Skips SENSEX (BFO — not on NSE).
    """
    global _cache_date
    today = datetime.now(IST).strftime("%Y-%m-%d")
    with _cache_lock:
        if _cache_date == today and _cache:
            log.debug("NSE prev-day OI cache already fresh for %s", today)
            return

    nse_symbols = [s for s in angel_symbols if s != "SENSEX"]
    log.info("Fetching prev-day OI from NSE for %d symbols…", len(nse_symbols))

    import requests
    session = _make_nse_session()
    if session is None:
        log.warning("Could not establish NSE session — prev-day OI unavailable")
        return

    new_cache: Dict[Tuple, int] = {}
    failed = []

    for angel_sym in nse_symbols:
        try:
            records = _fetch_option_chain(session, angel_sym)
            count   = _parse_into_cache(angel_sym, records, new_cache)
            log.info("  %-20s → %d strikes loaded", angel_sym, count)
            time.sleep(0.3)   # polite delay between requests
        except Exception as exc:
            log.warning("  %-20s → FAILED: %s", angel_sym, exc)
            failed.append(angel_sym)

    with _cache_lock:
        _cache.clear()
        _cache.update(new_cache)
        _cache_date = today

    log.info("NSE prev-day OI cache: %d entries  failed=%s", len(new_cache), failed or "none")


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_nse_session():
    """Create a requests.Session with NSE cookies."""
    import requests
    session = requests.Session()
    session.headers.update({
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36",
        "Accept":          "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer":         "https://www.nseindia.com/",
        "Connection":      "keep-alive",
    })
    try:
        session.get("https://www.nseindia.com", timeout=15)
        time.sleep(1.0)
        return session
    except Exception as exc:
        log.warning("NSE homepage request failed: %s", exc)
        return None


def _fetch_option_chain(session, angel_sym: str) -> list:
    """
    Fetch raw option chain data list from NSE API.
    Returns list of strike records (each may have 'CE', 'PE', 'strikePrice', 'expiryDate').
    """
    nse_sym = _SYMBOL_MAP.get(angel_sym, angel_sym)

    if angel_sym in _NSE_INDEX_SYMBOLS:
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={nse_sym}"
    else:
        url = f"https://www.nseindia.com/api/option-chain-equities?symbol={nse_sym}"

    r = session.get(url, timeout=15)
    r.raise_for_status()
    return r.json()["records"]["data"]


def _parse_into_cache(angel_sym: str, records: list, cache: dict) -> int:
    """
    Parse option chain records into cache dict.
    Key: (angel_sym, expiry_str, strike, opt_type)
    Value: prev_day_oi = openInterest - changeinOpenInterest
    Returns number of unique strikes parsed.
    """
    strikes_seen = set()

    for rec in records:
        strike     = int(rec.get("strikePrice", 0))
        expiry_raw = rec.get("expiryDate", "")       # e.g. "27-Mar-2026"
        expiry_str = _normalise_expiry(expiry_raw)   # → "27MAR26"
        if not expiry_str or not strike:
            continue

        for opt_type in ("CE", "PE"):
            leg = rec.get(opt_type)
            if not leg:
                continue
            oi       = int(leg.get("openInterest", 0))
            oi_chg   = int(leg.get("changeinOpenInterest", 0))
            prev_oi  = oi - oi_chg
            if prev_oi > 0:
                cache[(angel_sym, expiry_str, strike, opt_type)] = prev_oi
                strikes_seen.add(strike)

    return len(strikes_seen)


def _normalise_expiry(raw: str) -> str:
    """
    Convert NSE date formats to app's format (DDMMMYY).

    NSE returns: "27-Mar-2026"  →  "27MAR26"
    """
    if not raw:
        return ""
    try:
        # Try "DD-Mon-YYYY"
        dt = datetime.strptime(raw.strip(), "%d-%b-%Y")
        return dt.strftime("%d%b%y").upper()   # "27MAR26"
    except ValueError:
        pass
    # Already in app format?
    if len(raw) == 7 and raw[:2].isdigit():
        return raw.upper()
    return ""
