"""
Greeks — computed via py_vollib (Black-Scholes), not hand-derived.
No free API gives pre-computed Greeks for arbitrary strikes (same gap we
hit with historical IV rank), so this uses a library call on data you
already have from the chain: spot, strike, days to expiry, risk-free
rate, and each leg's own implied volatility.

Kept separate from analytics.py — that file stays 100% your hand-coded
work; this one is scaffolding, same spirit as the yfinance data pulls.
"""

from datetime import datetime
from py_vollib.black_scholes.greeks.analytical import delta, gamma, theta, vega


def compute_leg_greeks(
    option_type: str,      # "call" or "put"
    spot: float,
    strike: float,
    expiry: str,            # "YYYY-MM-DD"
    risk_free_rate: float,  # decimal, e.g. 0.05 for 5%
    iv: float,               # decimal, e.g. 0.25 for 25%
) -> dict:
    """
    Greeks for one leg, as if you bought it (raw per-contract values,
    sign not yet adjusted for long/short position).
    """
    flag = "c" if option_type == "call" else "p"
    days_to_expiry = (datetime.strptime(expiry, "%Y-%m-%d") - datetime.now()).days
    t = max(days_to_expiry, 1) / 365.0  # floor at 1 day to avoid t=0 blowing up the math

    return {
        "delta": delta(flag, spot, strike, t, risk_free_rate, iv),
        "gamma": gamma(flag, spot, strike, t, risk_free_rate, iv),
        "theta": theta(flag, spot, strike, t, risk_free_rate, iv),
        "vega": vega(flag, spot, strike, t, risk_free_rate, iv),
    }


def compute_spread_greeks(long_leg_greeks: dict, short_leg_greeks: dict) -> dict:
    """
    Net position Greeks for the spread: long leg contributes +1x,
    short leg contributes -1x, regardless of call/put or debit/credit —
    this part doesn't depend on the strike-position logic your payoff
    math uses, it's just long-minus-short on each Greek.
    """
    return {
        g: long_leg_greeks[g] - short_leg_greeks[g]
        for g in ("delta", "gamma", "theta", "vega")
    }
