import streamlit as st
import numpy as np
import plotly.graph_objects as go

from options_data import (
    get_available_expiries,
    get_leg_quote,
    fetch_vix,
    get_days_to_earnings,
)
from analytics import (
    compute_vertical_spread_payoff,
    compute_breakevens,
    compute_max_profit_loss,
    compute_iv_rank,
)

st.set_page_config(page_title="Options Trading Dashboard", page_icon="📈", layout="wide")
st.title("Options Trading Dashboard")

# ---- Sidebar: how many tickers to compare ----
num_tickers = st.sidebar.radio("Tickers to compare", [1, 2, 3], index=0)
tickers = []
for i in range(num_tickers):
    default = ["SPY", "QQQ", "NVDA"][i]
    tickers.append(st.sidebar.text_input(f"Ticker {i + 1}", value=default, key=f"ticker_{i}"))

vix = fetch_vix()


def render_ticker_panel(ticker: str):
    st.subheader(ticker)

    expiries = get_available_expiries(ticker)
    if not expiries:
        st.warning(f"No option chain available for {ticker}.")
        return

    expiry = st.selectbox("Expiry", expiries, key=f"expiry_{ticker}")
    option_type = st.radio("Type", ["call", "put"], key=f"type_{ticker}", horizontal=True)

    col_a, col_b = st.columns(2)
    with col_a:
        long_strike = st.number_input("Long strike", key=f"long_{ticker}", step=1.0)
    with col_b:
        short_strike = st.number_input("Short strike", key=f"short_{ticker}", step=1.0)

    if long_strike == 0 or short_strike == 0:
        st.info("Enter both strikes to see the payoff.")
        return

    long_leg = get_leg_quote(ticker, expiry, long_strike, option_type)
    short_leg = get_leg_quote(ticker, expiry, short_strike, option_type)

    if long_leg is None or short_leg is None:
        st.warning("One or both strikes not found in the chain — check the values.")
        return

    long_price = long_leg["lastPrice"]
    short_price = short_leg["lastPrice"]

    # --- payoff chart: calls into your analytics.py ---
    try:
        underlying_price = (long_strike + short_strike) / 2  # rough center for range; refine if you want spot price instead
        price_range = np.linspace(underlying_price * 0.85, underlying_price * 1.15, 200)
        pnl = compute_vertical_spread_payoff(
            long_strike, long_price, short_strike, short_price, option_type, price_range
        )
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=price_range, y=pnl, mode="lines", name="P&L"))
        fig.add_hline(y=0, line_dash="dot")
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    except NotImplementedError:
        st.info("Payoff chart will render once compute_vertical_spread_payoff is filled in (analytics.py).")

    # --- breakevens / max profit-loss ---
    try:
        breakevens = compute_breakevens(long_strike, long_price, short_strike, short_price, option_type)
        max_pl = compute_max_profit_loss(long_strike, long_price, short_strike, short_price, option_type)
        st.caption(
            f"Breakeven: {', '.join(f'{b:.2f}' for b in breakevens)}  |  "
            f"Max profit: {max_pl['max_profit']:.2f}  |  Max loss: {max_pl['max_loss']:.2f}"
        )
    except NotImplementedError:
        st.caption("Breakeven / max P&L will show once analytics.py is filled in.")

    # --- context metrics row ---
    try:
        iv_rank = compute_iv_rank(long_leg["impliedVolatility"], iv_history=None)
        iv_rank_display = f"{iv_rank:.0f}" if iv_rank is not None else "—"
    except NotImplementedError:
        iv_rank_display = "—"

    days_to_earnings = get_days_to_earnings(ticker)
    m1, m2, m3 = st.columns(3)
    m1.metric("IV rank", iv_rank_display)
    m2.metric("VIX", f"{vix:.1f}")
    m3.metric("Earnings in", f"{days_to_earnings}d" if days_to_earnings is not None else "—")


cols = st.columns(num_tickers)
for col, ticker in zip(cols, tickers):
    with col:
        if ticker:
            render_ticker_panel(ticker.upper())
