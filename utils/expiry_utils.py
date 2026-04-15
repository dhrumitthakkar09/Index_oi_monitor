"""
utils/expiry_utils.py — Detect current weekly/monthly expiry dates.

NSE weekly expiry rules (2024+):
  NIFTY        → Tuesday
  BANKNIFTY    → Tuesday
  SENSEX/BSE   → Thursday
  MIDCPNIFTY   → Monday

Monthly expiry = last Thursday of the month (NIFTY-style indices).
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

# NSE weekday of expiry per index  (Monday=0 … Sunday=6)
WEEKLY_EXPIRY_WEEKDAY: dict[str, int] = {
    "NIFTY":        1,   # Tuesday
    "BANKNIFTY":    1,   # Tuesday
    "SENSEX":       3,   # Thursday
    "MIDCAPSELECT": 0,   # Monday
}

MONTHLY_EXPIRY_WEEKDAY = 1   # Thursday (last Thu of month for most NSE contracts)


def _next_or_same_weekday(from_date: date, weekday: int) -> date:
    """Return `from_date` if it's already `weekday`, else the next occurrence."""
    days_ahead = (weekday - from_date.weekday()) % 7
    return from_date + timedelta(days=days_ahead)


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """Return the last occurrence of `weekday` in the given month."""
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    days_back = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=days_back)


def get_current_expiry(index_name: str, expiry_type: str = "weekly") -> date:
    """
    Return the nearest upcoming (or today if it is) expiry date for `index_name`.

    Parameters
    ----------
    index_name  : one of INDEX_CONFIG keys
    expiry_type : "weekly" | "monthly"
    """
    today = date.today()
    key   = index_name.upper()

    if expiry_type == "weekly":
        weekday   = WEEKLY_EXPIRY_WEEKDAY.get(key, 3)   # default Thursday
        candidate = _next_or_same_weekday(today, weekday)

        # On expiry day, roll to NEXT week's expiry at market open (09:15 IST).
        # Without this, OI drains to zero all afternoon as positions close,
        # causing false 100%+ DROP alerts on every poll cycle.
        if candidate == today:
            from datetime import datetime, timezone, timedelta
            IST      = timezone(timedelta(hours=5, minutes=30))
            ist_now  = datetime.now(IST)
            # Roll after 09:00 IST on expiry day (before OI starts draining)
            if ist_now.hour >= 9:
                candidate = _next_or_same_weekday(today + timedelta(days=1), weekday)

        return candidate

    # Monthly
    month_expiry = _last_weekday_of_month(today.year, today.month, MONTHLY_EXPIRY_WEEKDAY)
    if today > month_expiry:
        # Roll to next month
        if today.month == 12:
            month_expiry = _last_weekday_of_month(today.year + 1, 1, MONTHLY_EXPIRY_WEEKDAY)
        else:
            month_expiry = _last_weekday_of_month(today.year, today.month + 1, MONTHLY_EXPIRY_WEEKDAY)
    return month_expiry


def expiry_to_str(expiry: date, fmt: str = "%d%b%Y") -> str:
    """e.g.  21Feb2026"""
    return expiry.strftime(fmt).upper()


def expiry_to_nse_str(expiry: date) -> str:
    """NSE option symbol date part: 21FEB2026"""
    return expiry.strftime("%d%b%Y").upper()
