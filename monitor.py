"""
monitor.py — Generic OI monitoring engine used by both index and stock monitors.

BaseOIMonitor accepts any instrument_config dict (same schema as INDEX_CONFIG /
STOCK_CONFIG) so a single engine handles indices and F&O stocks without
code duplication.

Concrete sub-classes:
  OIMonitor       → indices  (INDEX_CONFIG)
  StockOIMonitor  → F&O stocks (STOCK_CONFIG)   ← see stock_monitor.py
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Tuple

import config
from alerts.telegram_alert import send_alert, send_info
from data_sources.base import BaseDataSource
from utils.csv_logger import log_oi_snapshot
from utils.expiry_utils import get_current_expiry, expiry_to_nse_str
from utils.logger import setup_logger
from utils.strike_utils import get_strike_set, StrikeSet

log = setup_logger("monitor")

OIKey  = Tuple[str, str, int, str]   # (name, expiry, strike, option_type)
OISnap = Dict[OIKey, int]


# ─────────────────────────────────────────────────────────────────────────────
# State container — one per instrument
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class InstrumentState:
    name:        str
    expiry:      str                    # e.g. "27FEB2026"
    strikes:     Optional[StrikeSet]    = None
    prev_atm:    Optional[int]          = None
    oi_snapshot: OISnap                 = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Base engine — all logic lives here
# ─────────────────────────────────────────────────────────────────────────────

class BaseOIMonitor:
    """
    Generic OI monitor.  Pass any instrument_config dict with the standard schema:

        {
          "SYMBOL": {
              "alert_threshold": int,       # % OI change to alert
              "strike_step":     int,       # distance between strikes
              "expiry_type":     str,       # "weekly" | "monthly"
              "yahoo_symbol":    str,
              "angel_symbol":    str,
              "dhan_symbol":     str,
          },
          ...
        }
    """

    def __init__(
        self,
        data_source:       BaseDataSource,
        instrument_config: dict,
        label:             str = "OI Monitor",
    ) -> None:
        self._ds     = data_source
        self._config = instrument_config
        self._label  = label

        self._stop_event = threading.Event()
        self._states: Dict[str, InstrumentState] = {}

    # ─────────────────────────────────────────────────────────────────────────
    # Public lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def start(self) -> None:
        log.info("%s starting …", self._label)
        # NOTE: data source is started once in main.py before monitors are created.
        # Do NOT call self._ds.start() here — it causes duplicate broker logins.

        for name, cfg in self._config.items():
            expiry  = get_current_expiry(name, cfg["expiry_type"])
            exp_str = expiry_to_nse_str(expiry)
            self._states[name] = InstrumentState(name=name, expiry=exp_str)
            log.info("  %-20s expiry=%-12s threshold=%d%%",
                     name, exp_str, cfg["alert_threshold"])

        send_info(
            f"✅ {self._label} started  |  Source: {config.DATA_SOURCE}\n"
            f"Watching: {', '.join(self._config.keys())}"
        )
        self._run_loop()

    def stop(self) -> None:
        log.info("%s stopping …", self._label)
        self._stop_event.set()
        self._ds.stop()
        send_info(f"🛑 {self._label} stopped")

    # ─────────────────────────────────────────────────────────────────────────
    # Main poll loop
    # ─────────────────────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        from datetime import timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))
        log.info("%s poll loop started | container UTC=%s  IST=%s",
                 self._label,
                 datetime.now(timezone.utc).strftime("%H:%M"),
                 datetime.now(IST).strftime("%H:%M"))
        while not self._stop_event.is_set():
            if config.RESPECT_MARKET_HOURS and not _is_market_open():
                log.debug("%s: market closed — sleeping 60s", self._label)
                self._stop_event.wait(timeout=60)
                continue

            # ── Batch-refresh all OI in ONE API call before per-symbol checks ──
            # This avoids 200+ individual calls per cycle that hit Angel One's
            # rate limiter and return silently-empty responses.
            if hasattr(self._ds, "batch_refresh_oi"):
                oi_requests = []
                for name, state in self._states.items():
                    spot = self._ds.get_spot_price(name)
                    if spot <= 0:
                        continue
                    cfg = self._config[name]
                    strikes = get_strike_set(spot, cfg["strike_step"])
                    for strike in (strikes.itm, strikes.atm, strikes.otm):
                        for opt_type in ("CE", "PE"):
                            oi_requests.append(
                                (name, state.expiry, strike, opt_type)
                            )
                try:
                    self._ds.batch_refresh_oi(oi_requests)
                except Exception:
                    log.exception("%s: batch OI refresh failed", self._label)

            for name in list(self._config.keys()):
                try:
                    self._process_instrument(name)
                except Exception:
                    log.exception("%s: unhandled error processing %s", self._label, name)

            self._stop_event.wait(timeout=config.POLL_INTERVAL_SECONDS)

    # ─────────────────────────────────────────────────────────────────────────
    # Per-instrument logic
    # ─────────────────────────────────────────────────────────────────────────

    def _process_instrument(self, name: str) -> None:
        cfg   = self._config[name]
        state = self._states[name]

        # ── 1. Roll expiry if needed ─────────────────────────────────────────
        fresh_expiry = expiry_to_nse_str(get_current_expiry(name, cfg["expiry_type"]))
        if fresh_expiry != state.expiry:
            log.info("%s expiry rolled: %s → %s", name, state.expiry, fresh_expiry)
            state.expiry      = fresh_expiry
            state.oi_snapshot = {}          # reset baseline on roll

        # ── 2. Spot price and strike set ─────────────────────────────────────
        spot = self._ds.get_spot_price(name)
        if spot <= 0:
            log.warning("%s: invalid spot (%.2f) — skipping", name, spot)
            return

        strikes = get_strike_set(spot, cfg["strike_step"])
        log.debug("%s  spot=%.2f  ATM=%d  ITM=%d  OTM=%d",
                  name, spot, strikes.atm, strikes.itm, strikes.otm)

        # ── 3. Dynamic ATM resubscription ────────────────────────────────────
        if strikes.atm != state.prev_atm:
            if state.prev_atm is not None:
                log.info("%s ATM changed %d → %d", name, state.prev_atm, strikes.atm)
                self._on_atm_change(name, strikes)
            state.prev_atm = strikes.atm
        state.strikes = strikes

        # ── 4. OI check: ITM / ATM / OTM × CE / PE ──────────────────────────
        for strike in (strikes.itm, strikes.atm, strikes.otm):
            for opt_type in ("CE", "PE"):
                self._check_oi(name, state, strike, opt_type, cfg)

    def _check_oi(
        self,
        name:     str,
        state:    InstrumentState,
        strike:   int,
        opt_type: str,
        cfg:      dict,
    ) -> None:
        key     = (name, state.expiry, strike, opt_type)
        new_oi  = self._ds.get_option_oi(name, state.expiry, strike, opt_type)
        prev_oi = state.oi_snapshot.get(key, 0)

        # ── Always log at INFO so alert pipeline is visible in normal logs ────
        # This replaces the old debug-only log — you can now see OI values
        # without changing LOG_LEVEL to DEBUG.
        if new_oi == 0 and prev_oi == 0:
            # First poll AND OI is 0 — likely NFO access issue or market closed
            log.info("OI %-15s %d %s  prev=%-8d new=%-8d  [no data yet]",
                     name, strike, opt_type, prev_oi, new_oi)
        elif new_oi == 0 and prev_oi > 0:
            # Had data before, now getting 0 — transient API issue
            log.warning("OI %-15s %d %s  prev=%-8d new=0  [data lost — keeping prev]",
                        name, strike, opt_type, prev_oi)
        else:
            log.info("OI %-15s %d %s  prev=%-8d new=%-8d",
                     name, strike, opt_type, prev_oi, new_oi)

        if prev_oi > 0 and new_oi > 0:
            pct = ((new_oi - prev_oi) / prev_oi) * 100.0

            log_oi_snapshot(
                index=name,
                expiry=state.expiry,
                strike=strike,
                option_type=opt_type,
                oi=new_oi,
                prev_oi=prev_oi,
                oi_change_pct=pct,
            )

            if abs(pct) >= cfg["alert_threshold"]:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log.warning("🚨 ALERT  %s %d %s  OI %+.1f%%  old=%d  new=%d",
                             name, strike, opt_type, pct, prev_oi, new_oi)
                send_alert(
                    index=name,
                    strike=strike,
                    option_type=opt_type,
                    oi_change=pct,
                    old_oi=prev_oi,
                    new_oi=new_oi,
                    timestamp=ts,
                )

        # Update snapshot — keep prev value if new is 0 (don't overwrite good data)
        if new_oi > 0:
            state.oi_snapshot[key] = new_oi

    # ─────────────────────────────────────────────────────────────────────────
    # ATM change hook
    # ─────────────────────────────────────────────────────────────────────────

    def _on_atm_change(self, name: str, new_strikes: StrikeSet) -> None:
        if hasattr(self._ds, "subscribe"):
            log.info("%s: WS resubscription triggered for new strikes "
                     "ITM=%d ATM=%d OTM=%d",
                     name, new_strikes.itm, new_strikes.atm, new_strikes.otm)
            # Token resolution is broker-specific; implement in data source


# ─────────────────────────────────────────────────────────────────────────────
# Concrete monitor for Index instruments
# ─────────────────────────────────────────────────────────────────────────────

class OIMonitor(BaseOIMonitor):
    """Index OI monitor — uses config.INDEX_CONFIG."""

    def __init__(self, data_source: BaseDataSource) -> None:
        super().__init__(
            data_source=data_source,
            instrument_config=config.INDEX_CONFIG,
            label="Index OI Monitor",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_market_open() -> bool:
    # Always use IST (UTC+5:30) regardless of Docker container timezone.
    # datetime.now() would use the container's local clock which is UTC
    # in most Docker setups — causing the market to appear closed during
    # actual trading hours (09:15–15:30 IST = 03:45–10:00 UTC).
    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST)
    if now.weekday() >= 5:          # Saturday=5, Sunday=6
        return False
    open_mins  = config.MARKET_OPEN_HOUR  * 60 + config.MARKET_OPEN_MINUTE
    close_mins = config.MARKET_CLOSE_HOUR * 60 + config.MARKET_CLOSE_MINUTE
    cur_mins   = now.hour * 60 + now.minute
    return open_mins <= cur_mins <= close_mins
