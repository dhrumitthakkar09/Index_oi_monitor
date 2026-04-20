"""
monitor.py — Generic OI monitoring engine used by the index monitor.

Baseline comparison: previous day's closing OI, persisted to disk.
  - After every poll cycle the current OI snapshot is saved to data/prev_day_oi.json.
  - On startup the file is loaded:
      date = yesterday  →  perfect prev-day baseline
      date = today      →  mid-session restart, used as best available baseline
      file missing      →  first run, prev_day shows n/a until tomorrow
  - Alerts fire when current OI deviates >= alert_threshold % from prev-day OI.

Fixes applied vs original:
  - FIX #2  : _prev_day_lock guards all read-modify-write on prev_day_oi.json
  - FIX #3  : BaseOIMonitor.stop() no longer calls ds.stop() — main.py owns the DS lifecycle
  - FIX #4  : Bootstrap saves the last trading day, not blindly "yesterday"
  - FIX #5  : warming_up cleared only after bootstrap thread finishes (stock path removed)
  - FIX #9  : daily alerted_keys reset moved to top of _process_instrument, not inside per-strike loop
  - FIX #10 : strike_range computed once per instrument per poll and passed through
  - FIX #11 : snapshot also saved on clean shutdown via stop()
  - FIX #14 : consecutive spot-fetch failure counter; Telegram alert after 3 consecutive misses
  - FIX #17 : _parse_key wrapped in try/except; malformed keys are skipped with a warning
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timezone, timedelta
from typing import Dict, Deque, Optional, Tuple

import config
from alerts.telegram_alert import send_alert, send_info, send_aggregate_trend_alert
from data_sources.base import BaseDataSource
from utils.csv_logger import log_oi_snapshot
from utils.expiry_utils import get_current_expiry, expiry_to_nse_str
from utils.logger import setup_logger
from utils.strike_utils import get_strike_set, get_strike_range, round_to_step, StrikeSet, NUM_STRIKES_EACH_SIDE

log = setup_logger("monitor")

IST = timezone(timedelta(hours=5, minutes=30))

_PREV_DAY_FILE = os.path.join(os.getenv("CSV_DIR", "data"), "prev_day_oi.json")

# FIX #2: single lock guards all reads and writes of prev_day_oi.json
_prev_day_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# Trading-day helpers
# ─────────────────────────────────────────────────────────────────────────────

def _last_trading_day(ref: datetime) -> str:
    """
    Return the most recent weekday on or before `ref` as YYYY-MM-DD.
    Does not account for public holidays (NSE holiday calendar not embedded),
    but correctly skips Saturday / Sunday.
    """
    d = ref.date()
    # Step back until we land on Mon–Fri
    while d.weekday() >= 5:   # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _prev_trading_day(ref: datetime) -> str:
    """
    Return the trading day immediately *before* `ref` (skips weekends).
    Used for bootstrap: if today is Monday we want Friday's data.
    """
    d = ref.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


# ─────────────────────────────────────────────────────────────────────────────
# Persistence helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_key(s: str) -> Optional[tuple]:
    """Parse a serialised OIKey string.  Returns None on any error (FIX #17)."""
    try:
        p = s.split("|")
        return (p[0], p[1], int(p[2]), p[3])
    except Exception as exc:
        log.warning("Skipping malformed prev-day key %r: %s", s, exc)
        return None


def _key(name: str, expiry: str, strike: int, opt_type: str) -> str:
    return f"{name}|{expiry}|{strike}|{opt_type}"


def _load_prev_day() -> tuple:
    """Returns (date_str, {OIKey: int}).  date_str may be '' if no file."""
    with _prev_day_lock:
        try:
            with open(_PREV_DAY_FILE) as f:
                d = json.load(f)
            snap = {}
            for k, v in d.get("oi", {}).items():
                parsed = _parse_key(k)
                if parsed is not None:
                    snap[parsed] = int(v)
            log.info("Prev-day OI loaded: date=%s  entries=%d", d.get("date", "?"), len(snap))
            return d.get("date", ""), snap
        except FileNotFoundError:
            log.info("No prev-day OI file — first run.  prev_day will show n/a today.")
            return "", {}
        except Exception as exc:
            log.warning("Failed to load prev-day OI: %s", exc)
            return "", {}


def _save_prev_day(date_str: str, snap: dict) -> None:
    """Thread-safe atomic save using rename.  (FIX #2)"""
    with _prev_day_lock:
        try:
            os.makedirs(os.path.dirname(_PREV_DAY_FILE) or ".", exist_ok=True)
            tmp = _PREV_DAY_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"date": date_str, "oi": {_key(*k): v for k, v in snap.items()}}, f)
            os.replace(tmp, _PREV_DAY_FILE)
        except Exception as exc:
            log.warning("Failed to save prev-day OI: %s", exc)


OIKey  = Tuple[str, str, int, str]   # (name, expiry, strike, option_type)
OISnap = Dict[OIKey, int]


# ─────────────────────────────────────────────────────────────────────────────
# State container — one per instrument
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class InstrumentState:
    name:           str
    expiry:         str                    # e.g. "27MAR26"
    strikes:        Optional[StrikeSet]    = None
    prev_atm:       Optional[int]          = None
    oi_snapshot:    OISnap                 = field(default_factory=dict)
    # alerted_keys stores (OIKey, direction, bucket) — see _check_oi for bucket logic
    alerted_keys:   set                    = field(default_factory=set)
    today_str:      Optional[str]          = None   # "YYYY-MM-DD" — resets alerted_keys daily
    warming_up:     bool                   = True   # True during first poll; suppresses alerts
    # FIX #14: track consecutive spot-fetch failures
    spot_fail_count: int                   = 0
    # Aggregate Trending OI across 4 open-price fixed strikes
    open_price:        Optional[float]  = None   # spot at first market-hours poll (day anchor)
    open_strikes:      Optional[list]   = None   # 4 strikes: open_atm + 0,1,2,3 × step
    agg_oi_history:    Optional[object] = None   # deque of (calls_oi, puts_oi, diff) tuples
    agg_trend_alerted: Optional[str]    = None   # "BULLISH" or "BEARISH" last alerted


# ─────────────────────────────────────────────────────────────────────────────
# Base engine
# ─────────────────────────────────────────────────────────────────────────────

class BaseOIMonitor:
    """
    Generic OI monitor.  Pass any instrument_config dict with the standard schema.

    Baseline comparison is against previous day's closing OI (loaded from disk
    at startup, saved after every poll cycle).

    NOTE: This class does NOT call ds.stop() — main.py owns the data-source
    lifecycle so two monitors sharing one ds don't race to shut it down. (FIX #3)
    """

    def __init__(
        self,
        data_source:        BaseDataSource,
        instrument_config:  dict,
        label:              str  = "OI Monitor",
        poll_interval:      Optional[int] = None,
        enable_trending_oi: bool = True,
    ) -> None:
        self._ds           = data_source
        self._config       = instrument_config
        self._label        = label
        self._poll_interval = poll_interval if poll_interval is not None else config.POLL_INTERVAL_SECONDS
        self._enable_trending_oi = enable_trending_oi

        self._stop_event = threading.Event()
        self._states: Dict[str, InstrumentState] = {}

        # Load prev-day baseline from disk
        self._prev_day_date, self._prev_day_oi = _load_prev_day()

    # ─────────────────────────────────────────────────────────────────────────
    # Public lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def start(self) -> None:
        log.info("%s starting …", self._label)

        for name, cfg in self._config.items():
            expiry  = get_current_expiry(name, cfg["expiry_type"])
            exp_str = expiry_to_nse_str(expiry)
            self._states[name] = InstrumentState(name=name, expiry=exp_str)
            log.info("  %-20s expiry=%-12s threshold=%d%%",
                     name, exp_str, cfg["alert_threshold"])

        today     = datetime.now(IST).strftime("%Y-%m-%d")
        yesterday = _prev_trading_day(datetime.now(IST))   # FIX #4: skip weekends

        my_instruments = set(self._config.keys())
        my_covered = sum(
            1 for (name, *_) in self._prev_day_oi
            if name in my_instruments
        )

        if self._prev_day_date in (today, yesterday) and my_covered > 0:
            log.info("Prev-day baseline OK: date=%s  my_instruments_covered=%d/%d",
                     self._prev_day_date, my_covered, len(my_instruments))
        else:
            log.warning(
                "Prev-day baseline insufficient for %s (file_date=%r, covered=%d/%d) — bootstrapping…",
                self._label, self._prev_day_date or "none", my_covered, len(my_instruments)
            )
            self._bootstrap_prev_day_from_candles()

        send_info(
            f"✅ {self._label} started  |  Source: {config.DATA_SOURCE}\n"
            f"Watching: {', '.join(self._config.keys())}"
        )
        self._run_loop()

    def stop(self) -> None:
        """
        Signal the poll loop to exit.
        Does NOT call ds.stop() — that is main.py's responsibility. (FIX #3)
        Saves the latest OI snapshot before exiting. (FIX #11)
        """
        log.info("%s stopping …", self._label)
        self._stop_event.set()
        self._save_snapshot()   # FIX #11: persist on clean shutdown
        # Note: Telegram stop alert is sent by main.py BEFORE ds.stop(),
        # not here, to ensure the HTTP session is still alive when it fires.

    # ─────────────────────────────────────────────────────────────────────────
    # Bootstrap from candle API
    # ─────────────────────────────────────────────────────────────────────────

    def _bootstrap_prev_day_from_candles(self) -> None:
        """
        Fetch previous trading day's closing OI from broker historical candle API
        for instruments in this monitor's own self._config only.

        FIX #4: uses _prev_trading_day() instead of blindly subtracting one day,
                so Monday correctly fetches Friday's data.
        FIX #5: warming_up cleared only after this function completes for small
                configs; large configs run in background but warming_up is left
                True until the thread finishes.
        """
        if not hasattr(self._ds, "fetch_prev_day_oi_from_candles"):
            log.warning("Bootstrap: data source has no candle API — skipping.")
            return

        from utils.strike_utils import get_strike_range

        is_large = len(self._config) > 10

        def _build_requests(n_strikes):
            reqs = []
            for name, cfg in self._config.items():
                spot  = self._ds.get_spot_price(name)
                state = self._states.get(name)
                if spot <= 0 or not state:
                    # For large configs (stocks), no spot at startup is expected —
                    # the first poll's batch_refresh_oi + _sync_prev_day_from_ds
                    # handles baseline population automatically.
                    (log.debug if is_large else log.warning)(
                        "Bootstrap: no spot/state for %s (spot=%.1f) — skip", name, spot
                    )
                    continue
                step = cfg["strike_step"]
                for strike in get_strike_range(spot, step, n=n_strikes):
                    for opt_type in ("CE", "PE"):
                        reqs.append((name, state.expiry, strike, opt_type))
            return reqs

        def _do_fetch(requests_list):
            if not requests_list:
                (log.debug if is_large else log.warning)(
                    "Bootstrap [%s]: no requests built — spot prices not yet available "
                    "(will be populated from first poll cycle).", self._label
                )
                return
            log.info("Bootstrap [%s]: fetching %d strikes from candle API…",
                     self._label, len(requests_list))
            fetched = self._ds.fetch_prev_day_oi_from_candles(requests_list)
            if fetched:
                # FIX #2: update shared dict then save atomically
                with _prev_day_lock:
                    self._prev_day_oi.update(fetched)
                    combined = dict(self._prev_day_oi)
                prev_date = _prev_trading_day(datetime.now(IST))   # FIX #4
                _save_prev_day(prev_date, combined)
                log.info("Bootstrap [%s]: %d entries loaded ✓", self._label, len(fetched))
                for k, oi in list(fetched.items())[:3]:
                    log.info("  Sample: %s %d %s prev_day_oi=%d", k[0], k[2], k[3], oi)
            else:
                log.warning("Bootstrap [%s]: candle API returned no OI data.", self._label)

        n_instruments = len(self._config)
        n_strikes     = 5 if n_instruments <= 10 else 3
        requests_list = _build_requests(n_strikes)

        if n_instruments <= 10:
            # Small config (indices): sync fetch — first poll has data immediately
            _do_fetch(requests_list)
            # warming_up stays True; cleared after first full poll in _run_loop
        else:
            # Large config: background fetch — don't block first poll
            # FIX #5: keep warming_up=True on all states until the thread finishes
            log.info("Bootstrap [%s]: launching background fetch (%d calls)…",
                     self._label, len(requests_list))

            def _bg():
                _do_fetch(requests_list)
                # Only now is the baseline ready — clear warmup
                for state in self._states.values():
                    state.warming_up = False
                log.info("Bootstrap [%s]: background fetch done; warmup cleared.", self._label)

            threading.Thread(
                target=_bg,
                name=f"OI-Bootstrap-{self._label}",
                daemon=True,
            ).start()
            # For large configs, _run_loop must NOT clear warming_up on first poll —
            # the background thread owns that transition.
            return   # signal to _run_loop via flag below

        # For small (sync) configs, _run_loop clears warming_up after the first poll.

    # ─────────────────────────────────────────────────────────────────────────
    # Main poll loop
    # ─────────────────────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        log.info("%s poll loop started | container UTC=%s  IST=%s",
                 self._label,
                 datetime.now(timezone.utc).strftime("%H:%M"),
                 datetime.now(IST).strftime("%H:%M"))

        # True for large-config monitors whose bootstrap runs in background.
        # For small configs, bootstrap is sync so this stays False.
        bg_bootstrap_running = len(self._config) > 10

        while not self._stop_event.is_set():
            if config.RESPECT_MARKET_HOURS and not _is_market_open():
                log.debug("%s: market closed — sleeping 60s", self._label)
                self._stop_event.wait(timeout=60)
                continue

            # ── Batch-refresh OI: ATM±1 strikes + open-price fixed strikes ──
            if hasattr(self._ds, "batch_refresh_oi"):
                seen: set        = set()
                oi_requests: list = []
                for name, state in self._states.items():
                    spot = self._ds.get_spot_price(name)
                    cfg  = self._config[name]
                    if spot <= 0:
                        # No spot yet — include a minimal request so batch_refresh_oi
                        # triggers the option chain fetch, which will populate spot.
                        req = (name, state.expiry, 0, "CE")
                        if req not in seen:
                            seen.add(req)
                            oi_requests.append(req)
                        continue
                    strikes = get_strike_set(spot, cfg["strike_step"])
                    # ATM ± 1 for spike detection
                    for strike in (strikes.itm, strikes.atm, strikes.otm):
                        for opt_type in ("CE", "PE"):
                            req = (name, state.expiry, strike, opt_type)
                            if req not in seen:
                                seen.add(req)
                                oi_requests.append(req)
                    # 4 open-price fixed strikes for aggregate trending (indices only)
                    if self._enable_trending_oi and state.open_strikes:
                        for strike in state.open_strikes:
                            for opt_type in ("CE", "PE"):
                                req = (name, state.expiry, strike, opt_type)
                                if req not in seen:
                                    seen.add(req)
                                    oi_requests.append(req)
                try:
                    self._ds.batch_refresh_oi(oi_requests)
                except Exception:
                    log.exception("%s: batch OI refresh failed", self._label)

                # Sync prev-day OI from DS cache for instruments that now have
                # spot data (e.g. stocks on Dhan whose OC was just fetched above)
                # but don't yet have a baseline in self._prev_day_oi.
                self._sync_prev_day_from_ds()

            # ── Per-instrument checks ─────────────────────────────────────────
            for name in list(self._config.keys()):
                try:
                    self._process_instrument(name)
                except Exception:
                    log.exception("%s: unhandled error processing %s", self._label, name)

            # FIX #5: only clear warming_up for sync-bootstrap (small) configs
            if not bg_bootstrap_running:
                for state in self._states.values():
                    state.warming_up = False

            # Save snapshot: at/after market close (FIX #11 also saves on stop())
            now_ist = datetime.now(IST)
            if now_ist.hour == 15 and now_ist.minute >= 20:
                self._save_snapshot()

            self._stop_event.wait(timeout=self._poll_interval)

    def _sync_prev_day_from_ds(self) -> None:
        """
        For instruments that now have a valid spot (e.g. stocks on Dhan whose
        option chain was just fetched) but no prev-day OI baseline in
        self._prev_day_oi yet, pull the previous_oi values directly from the
        data source's own cache (populated by the option chain response).

        This runs after every batch_refresh_oi so the very first OC fetch for
        each instrument automatically establishes its prev-day baseline — no
        separate bootstrap needed.
        """
        if not hasattr(self._ds, "fetch_prev_day_oi_from_candles"):
            return
        sync_reqs = []
        for name, state in self._states.items():
            spot = self._ds.get_spot_price(name)
            if spot <= 0:
                continue
            cfg = self._config[name]
            for strike in get_strike_range(spot, cfg["strike_step"], n=5):
                for opt_type in ("CE", "PE"):
                    key = (name, state.expiry, strike, opt_type)
                    if key not in self._prev_day_oi:
                        sync_reqs.append(key)
        if not sync_reqs:
            return
        try:
            fetched = self._ds.fetch_prev_day_oi_from_candles(sync_reqs)
        except Exception:
            log.exception("_sync_prev_day_from_ds failed")
            return
        if fetched:
            with _prev_day_lock:
                self._prev_day_oi.update(fetched)
            log.info("Synced %d prev-day OI entries from DS cache", len(fetched))

    def _save_snapshot(self) -> None:
        today = datetime.now(IST).strftime("%Y-%m-%d")
        combined = {}
        for state in self._states.values():
            combined.update(state.oi_snapshot)
        if combined:
            _save_prev_day(today, combined)

    # ─────────────────────────────────────────────────────────────────────────
    # Per-instrument logic
    # ─────────────────────────────────────────────────────────────────────────

    def _process_instrument(self, name: str) -> None:
        cfg   = self._config[name]
        state = self._states[name]

        # FIX #9: daily alerted_keys reset happens ONCE per instrument per poll,
        # not inside the per-strike loop where the clock can tick mid-cycle.
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        if state.today_str != today_str:
            state.alerted_keys     = set()
            state.open_price       = None
            state.open_strikes     = None
            state.agg_oi_history   = None
            state.agg_trend_alerted = None
            state.today_str        = today_str
            log.info("%s: new trading day — alerted_keys and trend state cleared", name)

        # ── 1. Roll expiry if needed ─────────────────────────────────────────
        fresh_expiry = expiry_to_nse_str(get_current_expiry(name, cfg["expiry_type"]))
        if fresh_expiry != state.expiry:
            log.info("%s expiry rolled: %s → %s", name, state.expiry, fresh_expiry)
            state.expiry      = fresh_expiry
            state.oi_snapshot = {}

        # ── 2. Spot price ────────────────────────────────────────────────────
        spot = self._ds.get_spot_price(name)
        if spot <= 0:
            state.spot_fail_count += 1
            log.warning("%s: invalid spot (%.2f) — skipping [fail #%d]",
                        name, spot, state.spot_fail_count)
            # FIX #14: alert after 3 consecutive failures
            if state.spot_fail_count == 3:
                send_info(f"⚠️ {name}: spot price unavailable for 3 consecutive polls. "
                          f"Check data source / broker connection.")
            return
        state.spot_fail_count = 0   # reset on success

        strikes = get_strike_set(spot, cfg["strike_step"])
        log.info("%s  spot=%.2f  ITM=%d  ATM=%d  OTM=%d",
                 name, spot, strikes.itm, strikes.atm, strikes.otm)

        # ── 3. Dynamic ATM resubscription ────────────────────────────────────
        if strikes.atm != state.prev_atm:
            if state.prev_atm is not None:
                log.info("%s ATM changed %d → %d", name, state.prev_atm, strikes.atm)
                self._on_atm_change(name, strikes)
            state.prev_atm = strikes.atm
        state.strikes = strikes

        # ── 4. OI check — ATM, 1 ITM, 1 OTM only ────────────────────────────
        for strike in (strikes.itm, strikes.atm, strikes.otm):
            for opt_type in ("CE", "PE"):
                self._check_oi(name, state, strike, opt_type, cfg)

        # ── 5 & 6. Trending OI — indices only ───────────────────────────────────
        if self._enable_trending_oi:
            if state.open_price is None and not state.warming_up:
                step               = cfg["strike_step"]
                atm                = round_to_step(spot, step)
                state.open_price   = spot
                state.open_strikes = [atm + i * step for i in range(4)]
                log.info(
                    "%s: open price captured=%.2f  open_strikes=%s",
                    name, spot, state.open_strikes,
                )
                send_info(
                    f"📌 {name} open price: {spot:,.2f}\n"
                    f"Tracking 4 strikes: {' · '.join(str(s) for s in state.open_strikes)}"
                )

            if state.open_strikes and not state.warming_up:
                self._check_aggregate_trend(name, state, cfg)

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

        # Prev-day OI baseline from disk
        prev_day_oi = self._prev_day_oi.get((name, state.expiry, strike, opt_type), 0)

        from_prev_day_pct = (
            ((new_oi - prev_day_oi) / prev_day_oi * 100.0)
            if prev_day_oi > 0 and new_oi > 0
            else None
        )
        from_prev_min_pct = (
            ((new_oi - prev_oi) / prev_oi * 100.0)
            if prev_oi > 0 and new_oi > 0
            else None
        )

        # ── Log line ──────────────────────────────────────────────────────────
        if new_oi == 0 and prev_oi == 0:
            log.info("OI %-15s %6d %s  prev_day=%-9s now=%-9d  [no data yet]",
                     name, strike, opt_type, "--", new_oi)
        elif new_oi == 0 and prev_oi > 0:
            log.warning("OI %-15s %6d %s  prev_day=%-9d now=0  [data lost]",
                        name, strike, opt_type, prev_day_oi)
        else:
            pd_str  = f"{prev_day_oi:<9d}" if prev_day_oi else "no-data  "
            fpd_str = f"{from_prev_day_pct:+.1f}%" if from_prev_day_pct is not None else "  n/a"
            fpm_str = f"{from_prev_min_pct:+.1f}%" if from_prev_min_pct is not None else "  n/a"
            log.info("OI %-15s %6d %s  prev_day=%-9s now=%-9d  from_prev_day=%7s  Δ1m=%7s",
                     name, strike, opt_type, pd_str, new_oi, fpd_str, fpm_str)

        # ── CSV logging ───────────────────────────────────────────────────────
        if prev_day_oi > 0 and new_oi > 0:
            log_oi_snapshot(
                index=name,
                expiry=state.expiry,
                strike=strike,
                option_type=opt_type,
                oi=new_oi,
                prev_oi=prev_day_oi,
                oi_change_pct=from_prev_day_pct,
            )

        # ── Alert: prev-day threshold ─────────────────────────────────────────
        # Fires ONCE per (strike, option_type, direction) per day — the first
        # time OI crosses the threshold.  alerted_keys is reset daily in
        # _process_instrument.  warming_up pre-populates the set so a restart
        # mid-session doesn't re-fire for an already-crossed strike.
        threshold = cfg["alert_threshold"]
        if from_prev_day_pct is not None and abs(from_prev_day_pct) >= threshold:
            direction = "UP" if from_prev_day_pct > 0 else "DN"
            alert_key = (key, direction)

            if state.warming_up:
                state.alerted_keys.add(alert_key)
            elif alert_key not in state.alerted_keys:
                ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

                # Classify OI pattern using price direction vs prev-day close
                spot      = self._ds.get_spot_price(name)
                prev_close = (
                    self._ds.get_prev_close(name)
                    if hasattr(self._ds, "get_prev_close") else 0.0
                )
                pattern = _classify_oi_pattern(spot, prev_close, from_prev_day_pct)

                log.warning(
                    "🚨 ALERT  %-12s %6d %s  OI vs prev-day %+.1f%%  "
                    "prev_day=%d  now=%d  pattern=%s",
                    name, strike, opt_type, from_prev_day_pct,
                    prev_day_oi, new_oi, pattern or "n/a",
                )
                send_alert(
                    index=name,
                    strike=strike,
                    option_type=opt_type,
                    oi_change=from_prev_day_pct,
                    crossed_threshold=threshold,
                    old_oi=prev_day_oi,
                    new_oi=new_oi,
                    timestamp=ts,
                    pattern=pattern,
                    spot=spot,
                    prev_close=prev_close,
                )
                state.alerted_keys.add(alert_key)

        # ── Update last-poll snapshot ─────────────────────────────────────────
        if new_oi > 0:
            state.oi_snapshot[key] = new_oi

    # ─────────────────────────────────────────────────────────────────────────
    # Aggregate Trending OI — 4 fixed open-price strikes
    # ─────────────────────────────────────────────────────────────────────────

    def _check_aggregate_trend(
        self,
        name:  str,
        state: InstrumentState,
        cfg:   dict,
    ) -> None:
        """
        Every poll: aggregate CALLS OI and PUTS OI across the 4 strikes that
        were fixed at the day's open price.  Track whether Calls OI or Puts OI
        is specifically rising across TREND_CONSECUTIVE_POLLS consecutive polls.

          Calls OI consistently rising → Call Writing dominant → BEARISH
          Puts  OI consistently rising → Put  Writing dominant → BULLISH

        Alert fires once per direction change; resets when trend breaks.
        PCR, DIFF%, and SENTIMENT are included in the Telegram message.
        """
        calls_oi = sum(
            self._ds.get_option_oi(name, state.expiry, s, "CE")
            for s in state.open_strikes
        )
        puts_oi = sum(
            self._ds.get_option_oi(name, state.expiry, s, "PE")
            for s in state.open_strikes
        )

        if calls_oi == 0 and puts_oi == 0:
            return

        total_oi = calls_oi + puts_oi
        pcr      = puts_oi / calls_oi if calls_oi > 0 else 0.0
        diff     = calls_oi - puts_oi
        diff_pct = diff / total_oi * 100.0 if total_oi > 0 else 0.0

        log.info(
            "AGG OI %-14s  calls=%10d  puts=%10d  diff=%+10d  diff%%=%+.1f%%  pcr=%.3f",
            name, calls_oi, puts_oi, diff, diff_pct, pcr,
        )

        n = config.TREND_CONSECUTIVE_POLLS
        if state.agg_oi_history is None:
            state.agg_oi_history = deque(maxlen=n + 1)

        state.agg_oi_history.append((calls_oi, puts_oi, diff))

        if len(state.agg_oi_history) < n + 1:
            return   # not enough history yet

        history = list(state.agg_oi_history)

        # Noise filter: each per-side step must shift by >= TREND_MIN_OI_CHANGE_PCT
        # of the current total OI to avoid firing on rounding noise.
        min_abs = total_oi * (config.TREND_MIN_OI_CHANGE_PCT / 100.0)

        # Track which side is specifically trending up across all consecutive polls.
        # This is more precise than tracking DIFF direction, which can move even
        # when the dominant side is unchanged (e.g. calls shrinking with puts flat).
        all_calls_up = all(
            history[i][0] > history[i - 1][0]
            and (history[i][0] - history[i - 1][0]) >= min_abs
            for i in range(1, len(history))
        )
        all_puts_up = all(
            history[i][1] > history[i - 1][1]
            and (history[i][1] - history[i - 1][1]) >= min_abs
            for i in range(1, len(history))
        )

        # Standard NSE interpretation:
        #   Calls OI consistently rising → Call Writing dominant → resistance → BEARISH
        #   Puts  OI consistently rising → Put  Writing dominant → support    → BULLISH
        if all_calls_up:
            trend_dir = "BEARISH"
        elif all_puts_up:
            trend_dir = "BULLISH"
        else:
            trend_dir = None

        if trend_dir is None:
            # Trend broken — let it fire fresh next time
            if state.agg_trend_alerted is not None:
                state.agg_trend_alerted = None
            return

        if trend_dir == state.agg_trend_alerted:
            return   # sustained trend already alerted; suppress repeat

        spot = self._ds.get_spot_price(name)
        ts   = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

        log.warning(
            "📊 AGG TREND  %-12s  dir=%s  calls=%d  puts=%d  pcr=%.3f  diff=%+d (%.1f%%)",
            name, trend_dir, calls_oi, puts_oi, pcr, diff, diff_pct,
        )
        send_aggregate_trend_alert(
            index=name,
            open_price=state.open_price,
            open_strikes=state.open_strikes,
            direction=trend_dir,
            calls_oi=calls_oi,
            puts_oi=puts_oi,
            pcr=pcr,
            diff=diff,
            diff_pct=diff_pct,
            oi_history=[(h[0], h[1]) for h in history],
            spot=spot,
            timestamp=ts,
        )
        state.agg_trend_alerted = trend_dir

    # ─────────────────────────────────────────────────────────────────────────
    # ATM change hook
    # ─────────────────────────────────────────────────────────────────────────

    def _on_atm_change(self, name: str, new_strikes: StrikeSet) -> None:
        if hasattr(self._ds, "subscribe"):
            log.info("%s: WS resubscription triggered for new strikes "
                     "ITM=%d ATM=%d OTM=%d",
                     name, new_strikes.itm, new_strikes.atm, new_strikes.otm)


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
    now = datetime.now(IST)
    if now.weekday() >= 5:          # Saturday=5, Sunday=6
        return False
    open_mins  = config.MARKET_OPEN_HOUR  * 60 + config.MARKET_OPEN_MINUTE
    close_mins = config.MARKET_CLOSE_HOUR * 60 + config.MARKET_CLOSE_MINUTE
    cur_mins   = now.hour * 60 + now.minute
    return open_mins <= cur_mins <= close_mins


def _classify_oi_pattern(
    spot:        float,
    prev_close:  float,
    oi_change:   float,   # % change vs prev-day (positive = increasing)
) -> str:
    """
    Classify the OI+Price combination per the standard F&O interpretation table:

    Price ↑  OI ↑  → Long Buildup    (bulls adding fresh longs)
    Price ↓  OI ↓  → Long Unwinding  (longs exiting)
    Price ↓  OI ↑  → Short Buildup   (bears adding fresh shorts)
    Price ↑  OI ↓  → Short Covering  (shorts exiting, covering)

    Returns one of: "Long Buildup", "Long Unwinding",
                    "Short Buildup", "Short Covering", or "" if indeterminate.
    """
    if prev_close <= 0 or spot <= 0:
        return ""
    price_up = spot > prev_close
    oi_up    = oi_change > 0
    if price_up and oi_up:
        return "Long Buildup"
    if not price_up and not oi_up:
        return "Long Unwinding"
    if not price_up and oi_up:
        return "Short Buildup"
    if price_up and not oi_up:
        return "Short Covering"
    return ""
