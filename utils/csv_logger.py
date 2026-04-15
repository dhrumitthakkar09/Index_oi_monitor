"""
utils/csv_logger.py — Append OI snapshots to per-index CSV files.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from threading import Lock

import config
from utils.logger import setup_logger

log  = setup_logger("csv_logger")
_lock = Lock()

HEADERS = [
    "timestamp", "index", "expiry", "strike", "option_type",
    "oi", "prev_oi", "oi_change_pct",
]


def _csv_path(index_name: str) -> str:
    os.makedirs(config.CSV_DIR, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(config.CSV_DIR, f"{index_name}_{date_str}.csv")


def log_oi_snapshot(
    index: str,
    expiry: str,
    strike: int,
    option_type: str,
    oi: int,
    prev_oi: int,
    oi_change_pct: float,
) -> None:
    if not config.CSV_ENABLED:
        return

    path = _csv_path(index)
    write_header = not os.path.exists(path)

    row = {
        "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "index":         index,
        "expiry":        expiry,
        "strike":        strike,
        "option_type":   option_type,
        "oi":            oi,
        "prev_oi":       prev_oi,
        "oi_change_pct": round(oi_change_pct, 2),
    }

    try:
        with _lock:
            with open(path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=HEADERS)
                if write_header:
                    writer.writeheader()
                writer.writerow(row)
    except Exception as exc:
        log.error("CSV write failed for %s: %s", index, exc)
