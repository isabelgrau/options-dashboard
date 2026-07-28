"""
Analytical core — this is yours to write.
Function signatures + docstrings below define the contract app.py expects.
Fill in the body of each function; don't need to touch app.py or options_data.py.
"""

import numpy as np
import pandas as pd


def compute_vertical_spread_payoff(
    long_strike: float,
    long_price: float,
    short_strike: float,
    short_price: float,
    option_type: str,       # "call" or "put"
    price_range: np.ndarray  # array of hypothetical underlying prices at expiration
) -> np.ndarray:
    """
    Return an array of P&L values (per contract, before multiplying by 100 and
    contract count) for each price in price_range, at expiration.

    app.py will call this as:
        prices = np.linspace(underlying_price * 0.85, underlying_price * 1.15, 200)
        pnl = compute_vertical_spread_payoff(
            long_strike, long_price, short_strike, short_price, option_type, prices
        )
    and plot prices vs. pnl directly.
    """
    raise NotImplementedError


def compute_breakevens(
    long_strike: float,
    long_price: float,
    short_strike: float,
    short_price: float,
    option_type: str
) -> list[float]:
    """
    Return the breakeven price(s) for the spread — usually one value for a
    2-leg vertical, but return a list for consistency in case you extend this.
    """
    raise NotImplementedError


def compute_max_profit_loss(
    long_strike: float,
    long_price: float,
    short_strike: float,
    short_price: float,
    option_type: str
) -> dict:
    """
    Return {"max_profit": float, "max_loss": float} per contract (pre-multiplier).
    """
    spread = abs(long_strike - short_strike)
    net_pmt = abs(long_price - short_price)

    # debit spreads
    # bull call spread - buy lower strike, sell higher strike
    # bear put spread - buy higher strike, sell lower strike
    if (option_type == 'call' and short_strike > long_strike) or (option_type == 'put' and short_strike < long_strike):
        max_profit = spread - net_pmt
        max_loss = -1 * net_pmt

    # credit spreads
    # bear call spread - sell lower strike, buy higher strike
    # bull put spread - sell higher strike, buy lower strike
    else:
        max_profit = net_pmt
        max_loss = net_pmt - spread
 
    return max_profit, max_loss
    
    raise NotImplementedError


def compute_iv_rank(
    current_iv: float,
    iv_history: pd.Series  # if you build one up over time; may be empty in v1
) -> float | None:
    """
    Return IV rank (0-100) given the current ATM IV and a historical IV series.

    Gotcha worth deciding now: yfinance doesn't expose historical daily IV out
    of the box, only the current chain's IV. Two realistic options for v1:
      1. Use historical volatility (HV, from close-to-close returns via
         options_data.fetch_price_history) as a proxy input instead of true
         historical IV — less precise but available today with no extra work.
      2. Return None / "insufficient history" for now, and let this populate
         properly once the v2 daily-snapshot logger has been running a while
         and you have real historical IV to rank against.
    Pick whichever you'd rather ship with — app.py just needs a float or None.
    """
    raise NotImplementedError
