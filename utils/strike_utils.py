"""
utils/strike_utils.py — ATM strike computation.

Monitoring window: ATM ± NUM_STRIKES steps on each side.
Wider window = more prev-day coverage for next day's ATM.
"""

from __future__ import annotations
from typing import NamedTuple, List


# ── How many strikes to monitor on each side of ATM ──────────────────────────
# ±5 means: 5 strikes below ATM, ATM itself, 5 strikes above ATM = 11 strikes.
# This ensures prev_day data is available even after a large overnight move.
NUM_STRIKES_EACH_SIDE = 5


class StrikeSet(NamedTuple):
    itm: int      # kept for backward compat — one step below ATM
    atm: int
    otm: int      # kept for backward compat — one step above ATM


def round_to_step(price: float, step: int) -> int:
    """Round price to nearest multiple of step."""
    return int(round(price / step) * step)


def get_strike_set(spot_price: float, strike_step: int) -> StrikeSet:
    """Returns the StrikeSet (itm, atm, otm) — kept for backward compat."""
    atm = round_to_step(spot_price, strike_step)
    return StrikeSet(
        itm=atm - strike_step,
        atm=atm,
        otm=atm + strike_step,
    )


def get_strike_range(spot_price: float, strike_step: int,
                     n: int = NUM_STRIKES_EACH_SIDE) -> List[int]:
    """
    Returns ATM ± n strikes.

    Example: spot=23450, step=50, n=5
    → [23200, 23250, 23300, 23350, 23400, 23450, 23500, 23550, 23600, 23650, 23700]

    This is what gets polled every minute AND saved at EOD.
    The wider range ensures prev_day OI is available even after a large
    overnight gap (e.g. 250 points = 5 × 50-step strikes for NIFTY).
    """
    atm = round_to_step(spot_price, strike_step)
    return [atm + i * strike_step for i in range(-n, n + 1)]
