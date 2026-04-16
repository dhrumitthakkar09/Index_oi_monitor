"""
main.py — Application entry point.

Runs two monitors concurrently:
  • Index OI Monitor  — NIFTY, SENSEX, BANKNIFTY, MIDCAP SELECT (main thread)
  • Stock OI Monitor  — all NSE F&O stocks in stock_config.py (daemon thread)

The data source is started ONCE here and shared.  main.py is the sole owner of
ds.start() / ds.stop() — monitors must NOT call ds.stop() themselves.

Usage:
    python main.py

Graceful shutdown: Ctrl+C  or  kill -SIGTERM <pid>
"""

from __future__ import annotations

import atexit
import os
import signal
import sys
import threading

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from data_sources import get_data_source          # noqa: E402
from monitor import OIMonitor                     # noqa: E402
from utils.logger import setup_logger             # noqa: E402

from stock_monitor import StockOIMonitor                  # noqa: E402

log = setup_logger("main")

# ── Stop-alert deduplication ──────────────────────────────────────────────────
_stop_notified = False


def _notify_stop() -> None:
    """Send the stop Telegram alert exactly once, regardless of exit path."""
    global _stop_notified
    if _stop_notified:
        return
    _stop_notified = True
    try:
        from alerts.telegram_alert import send_info as _si
        _si("🛑 OI Monitor stopped")
    except Exception as _e:
        log.warning("Stop alert failed: %s", _e)


atexit.register(_notify_stop)
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    log.info("=" * 60)
    log.info("  NSE / BSE  OI  SPIKE  MONITOR")
    log.info("=" * 60)

    import config
    log.info("Data source   : %s", config.DATA_SOURCE)
    log.info("Poll interval : %ds", config.POLL_INTERVAL_SECONDS)
    log.info("CSV logging   : %s", "ON" if config.CSV_ENABLED else "OFF")
    log.info("Market hours  : %s", "enforced" if config.RESPECT_MARKET_HOURS else "ignored")
    log.info("Indices       : %s", ", ".join(config.INDEX_CONFIG.keys()))
    log.info("F&O Stocks    : %d stocks  poll=%ds",
             len(__import__("stock_config").STOCK_CONFIG),
             config.STOCK_POLL_INTERVAL_SECONDS)

    # ── Start data source ONCE — owned exclusively by main.py ────────────────
    ds = get_data_source()
    log.info("Starting data source (%s) …", config.DATA_SOURCE)
    ds.start()
    log.info("Data source ready")

    # ── Index monitor ─────────────────────────────────────────────────────────
    index_monitor = OIMonitor(ds)

    # ── Stock monitor (daemon thread) ─────────────────────────────────────────
    stock_monitor = StockOIMonitor(ds)
    stock_thread  = threading.Thread(
        target=_run_monitor,
        args=(stock_monitor, "Stock"),
        name="StockMonitor",
        daemon=True,
    )
    stock_thread.start()
    log.info("Stock OI Monitor thread started")

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    # FIX #3: ds.stop() is called HERE — not inside monitor.stop()
    def _shutdown(signum, frame):
        log.info("Shutdown signal (%s) received — stopping …", signum)
        _notify_stop()
        index_monitor.stop()
        stock_monitor.stop()
        ds.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # ── Run index monitor on main thread (blocking) ───────────────────────────
    try:
        index_monitor.start()
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt — shutting down")
        _notify_stop()
        index_monitor.stop()
        stock_monitor.stop()
        ds.stop()
    except Exception as exc:
        log.critical("Index monitor fatal error: %s", exc, exc_info=True)
        global _stop_notified
        _stop_notified = True   # suppress duplicate "stopped" from atexit
        try:
            from alerts.telegram_alert import send_info as _si
            _si(f"💥 OI Monitor CRASHED: {exc}")
        except Exception as _e:
            log.warning("Crash alert failed: %s", _e)
        index_monitor.stop()
        stock_monitor.stop()
        ds.stop()
        sys.exit(1)


def _run_monitor(monitor, label: str) -> None:
    """Thread target — wraps monitor.start() with top-level exception logging."""
    try:
        monitor.start()
    except Exception as exc:
        log.critical("%s monitor fatal error: %s", label, exc, exc_info=True)


if __name__ == "__main__":
    main()
