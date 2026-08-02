"""
Scaffolding layer: pulls raw market data for the options dashboard.
No analytical judgment lives here — just fetching and light shaping.
"""

import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime

# Cache TTLs are deliberately short — long enough to kill repeat calls while
# you're tweaking strikes on the same page load, short enough that you're not
# looking at stale prices if you come back later in the day.
CHAIN_CACHE_TTL = 5 * 60   # 5 min — chain data (strikes, IV) moves during market hours
VIX_CACHE_TTL = 5 * 60     # 5 min
EARNINGS_CACHE_TTL = 60 * 60 * 12  # 12 hr — earnings dates don't move intraday


@st.cache_data(ttl=CHAIN_CACHE_TTL)
def get_available_expiries(ticker: str) -> list[str]:
    """Return list of expiry date strings (YYYY-MM-DD) available for the ticker."""
    tk = yf.Ticker(ticker)
    return list(tk.options)


@st.cache_data(ttl=CHAIN_CACHE_TTL)
def fetch_option_chain(ticker: str, expiry: str) -> dict:
    """
    Pull the full chain for one expiry.

    Returns:
        {"calls": DataFrame, "puts": DataFrame}

    Each DataFrame has yfinance's native columns — the ones you'll care about:
        strike, lastPrice, bid, ask, impliedVolatility, openInterest, volume
    """
    tk = yf.Ticker(ticker)
    chain = tk.option_chain(expiry)
    return {"calls": chain.calls, "puts": chain.puts}


def get_leg_quote(ticker: str, expiry: str, strike: float, option_type: str) -> dict:
    """
    Convenience lookup for a single leg (one strike, one side) from the chain.

    option_type: "call" or "put"

    Returns a dict with at least: strike, lastPrice, bid, ask, impliedVolatility
    Returns None if the strike isn't found (e.g. bad strike input).
    """
    side = fetch_option_chain(ticker, expiry)["calls" if option_type == "call" else "puts"]
    row = side[side["strike"] == strike]
    if row.empty:
        return None
    return row.iloc[0].to_dict()


@st.cache_data(ttl=EARNINGS_CACHE_TTL)  # company name basically never changes; reuse the long TTL
def get_company_name(ticker: str) -> str:
    """Return the company's full name, or the ticker itself if unavailable."""
    tk = yf.Ticker(ticker)
    try:
        return tk.info.get("longName", ticker)
    except Exception:
        return ticker


@st.cache_data(ttl=VIX_CACHE_TTL)
def fetch_current_price(ticker: str) -> float | None:
    """Most recent close price for the ticker — used to mark spot price on the payoff chart."""
    tk = yf.Ticker(ticker)
    hist = tk.history(period="5d")
    if hist.empty:
        return None
    return float(hist["Close"].iloc[-1])


@st.cache_data(ttl=VIX_CACHE_TTL)
def fetch_risk_free_rate() -> float:
    """
    13-week Treasury bill yield (^IRX), as a decimal (e.g. 0.052 for 5.2%).
    Used as the risk-free rate input for Greeks — a standard proxy for
    short-dated options; not exact for every expiry, but the Greeks
    aren't very sensitive to small changes in this input.
    """
    tbill = yf.Ticker("^IRX")
    hist = tbill.history(period="5d")
    return float(hist["Close"].iloc[-1]) / 100


@st.cache_data(ttl=VIX_CACHE_TTL)
def fetch_vix() -> float:
    """Current VIX close (most recent available trading day)."""
    vix = yf.Ticker("^VIX")
    hist = vix.history(period="5d")
    return float(hist["Close"].iloc[-1])


@st.cache_data(ttl=CHAIN_CACHE_TTL)
def fetch_price_history(ticker: str, period: str = "1y") -> pd.Series:
    """
    Daily close price history — the raw input for historical volatility (HV),
    which you'll compute yourself in analytics.py.
    """
    tk = yf.Ticker(ticker)
    hist = tk.history(period=period)
    return hist["Close"]


@st.cache_data(ttl=EARNINGS_CACHE_TTL)
def get_days_to_earnings(ticker: str) -> int | None:
    """
    Days from today to the next scheduled earnings date, or None if unavailable.

    Gotcha: yfinance's earnings_dates can return past AND future dates, and
    occasionally comes back empty depending on the ticker and yfinance version.
    This filters to future dates only and takes the nearest one.
    """
    tk = yf.Ticker(ticker)
    try:
        dates = tk.earnings_dates
    except (KeyError, IndexError, ValueError):
        # Genuinely "no earnings data available" cases from yfinance's side.
        return None
    # Anything else (missing dependency, network error, etc.) will now raise
    # and show up as a real Streamlit error instead of a silent "—".
    if dates is None or dates.empty:
        return None

    today = pd.Timestamp.now(tz=dates.index.tz)
    future = dates[dates.index >= today]
    if future.empty:
        return None

    next_date = future.index.min()
    return (next_date - today).days
