"""
utils/strike_utils.py — ATM / ITM / OTM strike computation.
"""

from __future__ import annotations
from typing import NamedTuple


class StrikeSet(NamedTuple):
    itm: int      # In-The-Money  (1 step below ATM for CE / above for PE)
    atm: int      # At-The-Money
    otm: int      # Out-Of-The-Money (1 step above ATM for CE / below for PE)


def round_to_step(price: float, step: int) -> int:
    """Round price to nearest multiple of step."""
    return int(round(price / step) * step)


def get_strike_set(spot_price: float, strike_step: int) -> StrikeSet:
    """
    Returns ATM and one strike on each side.

    For CE perspective:
        ITM = ATM - step
        OTM = ATM + step

    (For PE, caller can invert if needed; we return symmetric set.)
    """
    atm = round_to_step(spot_price, strike_step)
    return StrikeSet(
        itm=atm - strike_step,
        atm=atm,
        otm=atm + strike_step,
    )
