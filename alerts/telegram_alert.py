"""
alerts/telegram_alert.py — Telegram bot dispatcher for OI Monitor.

Alert format example:
  🚨 Long Buildup
  ──────────────────────────────
  Index   : NIFTY
  Strike  : 23750 CE
  OI Chg  : ▲ +542.0%
  Prev OI : 12,000
  Curr OI : 77,040
  Spot    : 23,712
  Time    : 2026-03-18 10:45:02
"""

from __future__ import annotations

import logging
import requests

import config

log = logging.getLogger("telegram_alert")

_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


def _send(text: str, timeout: int = 5) -> bool:
    """Send a Telegram message. Returns True on success.
    Uses a short timeout (default 5s) so stop alerts complete before
    Docker's stop grace period expires.
    """
    token   = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        log.debug("Telegram not configured — skipping message")
        return False
    try:
        resp = requests.post(
            _API_BASE.format(token=token),
            json={
                "chat_id":    chat_id,
                "text":       text,
                "parse_mode": "HTML",
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        log.warning("Telegram send failed: %s", exc)
        return False


def send_alert(
    index:             str,
    strike:            int,
    option_type:       str,
    oi_change:         float,
    crossed_threshold: int,
    old_oi:            int,
    new_oi:            int,
    timestamp:         str,
    pattern:           str = "",
    spot:              float = 0.0,
    prev_close:        float = 0.0,
) -> None:
    """Send an OI spike alert."""
    oi_dir = "▲" if oi_change > 0 else "▼"
    header = f"🚨 {pattern}" if pattern else "🚨 OI ALERT"

    text = (
        f"{header}\n"
        f"{'─' * 30}\n"
        f"Index   : <b>{index}</b>\n"
        f"Strike  : <b>{strike:,} {option_type}</b>\n"
        f"OI Chg  : {oi_dir} <b>{oi_change:+.1f}%</b>\n"
        f"Prev OI : {old_oi:,}\n"
        f"Curr OI : {new_oi:,}\n"
    )
    if spot > 0:
        text += f"Spot    : {spot:,.0f}\n"
    text += f"Time    : {timestamp}"

    ok = _send(text)
    if ok:
        log.info("Telegram alert sent: %s %d %s OI %+.1f%%  pattern=%s",
                 index, strike, option_type, oi_change, pattern or "n/a")


def send_aggregate_trend_alert(
    index:        str,
    open_price:   float,
    open_strikes: list,       # 4 strikes fixed at open price
    direction:    str,        # "BULLISH" or "BEARISH"
    calls_oi:     int,
    puts_oi:      int,
    pcr:          float,
    diff:         int,        # calls_oi - puts_oi
    diff_pct:     float,      # diff as % of total OI
    oi_history:   list,       # list of (calls_oi, puts_oi) tuples, oldest → newest
    spot:         float = 0.0,
    timestamp:    str   = "",
) -> None:
    """
    Send an aggregate trending-OI alert based on 4 open-price fixed strikes.
    Mirrors the Trending OI Data table from the NSE OI tracker.
    """
    n_polls     = len(oi_history) - 1
    strikes_str = " · ".join(f"{s:,}" for s in open_strikes)
    diff_path   = " → ".join(f"{h[0] - h[1]:+,}" for h in oi_history)

    if direction == "BULLISH":
        # DIFF falling → Puts side gaining ground relative to Calls
        arrow     = "📈"
        what      = "Put Writing Rising"
        poll_desc = "consecutive DIFF falling ticks"
    else:
        # DIFF rising → Calls side gaining ground relative to Puts
        arrow     = "📉"
        what      = "Call Writing Rising"
        poll_desc = "consecutive DIFF rising ticks"

    # Sentiment based on current snapshot: which side currently dominates (NSE table logic)
    # PCR >= 1 → Puts >= Calls → Bullish;  PCR < 1 → Calls > Puts → Bearish
    sentiment = "🟢 Bullish" if pcr >= 1.0 else "🔴 Bearish"

    text = (
        f"{arrow} <b>{index}</b> OI Trending — {what}\n"
        f"{'─' * 30}\n"
        f"Open Price : {open_price:,.2f}\n"
        f"Strikes    : {strikes_str}\n"
        f"Calls OI   : {calls_oi:,}\n"
        f"Puts OI    : {puts_oi:,}\n"
        f"DIFF (C−P) : {diff:+,}  ({diff_pct:+.1f}%)\n"
        f"PCR        : {pcr:.3f}\n"
        f"Polls      : {n_polls} {poll_desc}\n"
        f"DIFF path  : {diff_path}\n"
        f"Sentiment  : {sentiment}\n"
    )
    if spot > 0:
        text += f"Spot       : {spot:,.0f}\n"
    if timestamp:
        text += f"Time       : {timestamp}"

    ok = _send(text)
    if ok:
        log.info(
            "Telegram agg-trend alert: %s  dir=%s  pcr=%.3f  diff=%+d (%.1f%%)",
            index, direction, pcr, diff, diff_pct,
        )


def send_info(message: str) -> None:
    """Send a plain informational message (startup, shutdown, warnings)."""
    ok = _send(message)
    if ok:
        log.info("Telegram info sent: %s", message[:80])
