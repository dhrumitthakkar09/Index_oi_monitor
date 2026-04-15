"""
alerts/telegram_alert.py — Telegram alert dispatcher.

Sends formatted OI spike alerts via the Telegram Bot API.
Retries up to 3 times on network failure.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

import requests

import config
from utils.logger import setup_logger

log = setup_logger("telegram_alert")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_RETRIES  = 3
RETRY_DELAY  = 2   # seconds between retries


def _build_message(
    index:       str,
    strike:      int,
    option_type: str,
    oi_change:   float,
    old_oi:      int,
    new_oi:      int,
    timestamp:   Optional[str] = None,
) -> str:
    import config
    import stock_config
    ts         = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_stock   = index in stock_config.STOCK_CONFIG
    label      = "STOCK" if is_stock else "INDEX"
    return (
        f"🚨 *OI SPIKE ALERT — {label}*\n"
        f"Symbol: *{index}*\n"
        f"Strike: *{strike} {option_type}*\n"
        f"OI Change: *{oi_change:.1f}%*\n"
        f"Old OI: `{old_oi:,}`\n"
        f"New OI: `{new_oi:,}`\n"
        f"Time: `{ts}`"
    )


def send_alert(
    index:       str,
    strike:      int,
    option_type: str,
    oi_change:   float,
    old_oi:      int,
    new_oi:      int,
    timestamp:   Optional[str] = None,
) -> bool:
    """
    Send a Telegram alert message.

    Returns True on success, False on failure.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.warning(
            "Telegram credentials not set — alert suppressed for %s %d %s",
            index, strike, option_type,
        )
        # Still log the alert locally
        log.info(
            "ALERT | %s | %d %s | OI change %.1f%% | old=%d new=%d",
            index, strike, option_type, oi_change, old_oi, new_oi,
        )
        return False

    message = _build_message(index, strike, option_type, oi_change, old_oi, new_oi, timestamp)
    url     = TELEGRAM_API.format(token=config.TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id":    config.TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "Markdown",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            log.info(
                "Telegram alert sent: %s %d %s OI +%.1f%%",
                index, strike, option_type, oi_change,
            )
            return True
        except requests.RequestException as exc:
            log.error("Telegram send attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    log.critical("Telegram alert failed after %d attempts", MAX_RETRIES)
    return False


def send_info(text: str) -> None:
    """Send a plain informational message to Telegram (startup/shutdown notices)."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return
    url     = TELEGRAM_API.format(token=config.TELEGRAM_BOT_TOKEN)
    payload = {"chat_id": config.TELEGRAM_CHAT_ID, "text": text}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as exc:
        log.error("Info message send failed: %s", exc)
