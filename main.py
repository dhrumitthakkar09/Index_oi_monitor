"""
main.py — Application entry point.

Runs two monitors concurrently in separate threads:
  • Index OI Monitor  — NIFTY, SENSEX, BANKNIFTY, MIDCAP SELECT  (weekly expiry)
  • Stock OI Monitor  — 34 F&O stocks                            (monthly expiry)

The data source is started ONCE here, then shared by both monitors.
This avoids double-authentication rate limit errors on broker APIs.

Usage:
    python main.py

Graceful shutdown: Ctrl+C  or  kill -SIGTERM <pid>
"""

from __future__ import annotations

import os
import signal
import sys
import threading

# ── Project root on sys.path before any local imports ────────────────────────
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from data_sources import get_data_source          # noqa: E402
from monitor import OIMonitor                     # noqa: E402
from stock_monitor import StockOIMonitor          # noqa: E402
from utils.logger import setup_logger             # noqa: E402

log = setup_logger("main")


def main() -> None:
    log.info("=" * 60)
    log.info("  NSE / BSE  OI  SPIKE  MONITOR  (Index + F&O Stocks)")
    log.info("=" * 60)

    import config
    import stock_config
    log.info("Data source   : %s", config.DATA_SOURCE)
    log.info("Poll interval : %ds", config.POLL_INTERVAL_SECONDS)
    log.info("CSV logging   : %s", "ON" if config.CSV_ENABLED else "OFF")
    log.info("Market hours  : %s", "enforced" if config.RESPECT_MARKET_HOURS else "ignored")
    log.info("Indices       : %s", ", ".join(config.INDEX_CONFIG.keys()))
    log.info("F&O Stocks    : %d configured", len(stock_config.STOCK_CONFIG))

    # ── Start data source ONCE — shared by both monitors ─────────────────────
    # IMPORTANT: Never call ds.start() again inside the monitors.
    # Calling it twice causes duplicate broker logins → "Access rate exceeded".
    ds = get_data_source()
    log.info("Starting data source (%s) …", config.DATA_SOURCE)
    ds.start()
    log.info("Data source ready")

    # ── Two monitor instances sharing the same live connection ────────────────
    index_monitor = OIMonitor(ds)
    stock_monitor = StockOIMonitor(ds)

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    def _shutdown(signum, frame):
        log.info("Shutdown signal (%s) received — stopping …", signum)
        index_monitor.stop()
        stock_monitor.stop()
        ds.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # ── Launch stock monitor in a background thread ───────────────────────────
    stock_thread = threading.Thread(
        target=_run_monitor,
        args=(stock_monitor, "Stock"),
        name="StockMonitor",
        daemon=True,
    )
    stock_thread.start()
    log.info("Stock OI Monitor thread started")

    # ── Run index monitor on main thread (blocking) ───────────────────────────
    try:
        index_monitor.start()
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt — shutting down")
        index_monitor.stop()
        stock_monitor.stop()
        ds.stop()
    except Exception as exc:
        log.critical("Index monitor fatal error: %s", exc, exc_info=True)
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
