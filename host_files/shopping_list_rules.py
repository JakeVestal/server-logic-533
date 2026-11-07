#!/usr/bin/env python3
"""
Shopping-list population rules.

For each tracked underlying:
- All expiries < 6 months from today
- Plus the expiry nearest to 1 year
- Plus the expiry nearest to 2 years
- Strikes within ±30% of the underlying's last close

Discovery of the raw chain is still required (LSEG). This module
filters a discovered chain down to the shopping-list set.
"""
from datetime import date, timedelta
from typing import Iterable


def select_expiries(available: Iterable[date], today: date | None = None) -> list[date]:
    today = today or date.today()
    available = sorted(set(available))
    short = [e for e in available if e <= today + timedelta(days=183)]
    def nearest(target_days: int) -> date | None:
        target = today + timedelta(days=target_days)
        cands = [e for e in available if e > today]
        if not cands:
            return None
        return min(cands, key=lambda e: abs((e - target).days))
    one_y = nearest(365)
    two_y = nearest(730)
    out = set(short)
    if one_y:
        out.add(one_y)
    if two_y:
        out.add(two_y)
    return sorted(out)


def select_strikes(available: Iterable[float], last_close: float, band: float = 0.30) -> list[float]:
    lo = last_close * (1 - band)
    hi = last_close * (1 + band)
    return sorted({s for s in available if lo <= s <= hi})


def filter_chain(chain_rows: list[dict], last_close: float, today: date | None = None) -> list[dict]:
    """
    chain_rows: list of {underlying, expiry, strike}
    Returns the subset that belongs on the shopping list.
    """
    today = today or date.today()
    expiries = select_expiries({r["expiry"] for r in chain_rows}, today)
    strikes = select_strikes({r["strike"] for r in chain_rows}, last_close)
    exp_set = set(expiries)
    strike_set = set(strikes)
    return [
        r for r in chain_rows
        if r["expiry"] in exp_set and r["strike"] in strike_set
    ]
