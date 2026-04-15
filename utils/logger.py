"""
utils/logger.py — Centralised logging setup (file + console).
"""

import logging
import os
from logging.handlers import RotatingFileHandler

import config


def setup_logger(name: str = "oi_monitor") -> logging.Logger:
    """
    Create and return a logger with:
    - RotatingFileHandler  (10 MB max, 5 backups)
    - StreamHandler        (console)
    """
    os.makedirs(config.LOG_DIR, exist_ok=True)

    logger = logging.getLogger(name)

    if logger.handlers:          # avoid duplicate handlers on re-import
        return logger

    logger.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── File handler ────────────────────────────────────────────────────────
    fh = RotatingFileHandler(
        config.LOG_FILE,
        maxBytes=10 * 1024 * 1024,   # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    fh.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))

    # ── Console handler ─────────────────────────────────────────────────────
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# Module-level default logger
log = setup_logger()
