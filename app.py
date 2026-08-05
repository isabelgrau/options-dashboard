import streamlit as st
import numpy as np
import plotly.graph_objects as go

from options_data import (
    get_available_expiries,
    get_leg_quote,
    get_company_name,
    fetch_current_price,
    fetch_vix,
    fetch_risk_free_rate,
    get_days_to_earnings,
)
from greeks import compute_leg_greeks, compute_spread_greeks
from sheets_log import log_snapshot_if_new
from analytics import (
    compute_vertical_spread_payoff,
    compute_breakevens,
    compute_max_profit_loss,
)

st.set_page_config(page_title="Options Trading Dashboard", page_icon="📈", layout="wide")
st.title("Options Trading Dashboard")

# ---- Owner check: gates logging only, never access to the app itself ----
owner_key = st.sidebar.text_input("Owner key", type="password", help="Leave blank unless you're the dashboard owner.")
is_owner = bool(owner_key) and owner_key == st.secrets.get("owner_passphrase", None)

# ---- Sidebar: how many tickers to compare ----
num_tickers = st.sidebar.radio("Tickers to compare", [1, 2, 3], index=0)
tickers = []
for i in range(num_tickers):
    default = ["SPY", "QQQ", "NVDA"][i]
    tickers.append(st.sidebar.text_input(f"Ticker {i + 1}", value=default, key=f"ticker_{i}"))

vix = fetch_vix()
risk_free_rate = fetch_risk_free_rate()
st.caption(f"VIX: {vix:.1f}")


def render_ticker_panel(ticker: str):
    st.subheader(ticker)
    st.caption(get_company_name(ticker))

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
    spot_price = None
    try:
        strike_low = min(long_strike, short_strike)
        strike_high = max(long_strike, short_strike)
        padding = (strike_high - strike_low) * 0.3  # ensures flat regions are always visible
        price_range = np.linspace(strike_low - padding, strike_high + padding, 200)
        pnl = compute_vertical_spread_payoff(
            long_strike, long_price, short_strike, short_price, option_type, price_range
        )
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=price_range, y=pnl, mode="lines", name="P&L"))
        fig.add_hline(y=0, line_dash="dot")
        spot_price = fetch_current_price(ticker)
        if spot_price is not None:
            fig.add_vline(
                x=spot_price, line_dash="dash", line_color="gray",
                annotation_text=f"Spot {spot_price:.2f}", annotation_position="top"
            )
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=35, b=10))
        st.plotly_chart(fig, use_container_width=True)
    except NotImplementedError:
        st.info("Payoff chart will render once compute_vertical_spread_payoff is filled in (analytics.py).")

    # --- breakevens / max profit-loss ---
    breakevens = None
    max_pl = None
    try:
        breakevens = compute_breakevens(long_strike, long_price, short_strike, short_price, option_type)
        max_pl = compute_max_profit_loss(long_strike, long_price, short_strike, short_price, option_type)
        st.caption(
            f"Breakeven: {breakevens:.2f}  |  "
            f"Max profit: {max_pl['max_profit']:.2f}  |  Max loss: {max_pl['max_loss']:.2f}"
        )
    except NotImplementedError:
        st.caption("Breakeven / max P&L will show once analytics.py is filled in.")

    # --- context metrics row ---
    iv = long_leg.get("impliedVolatility")
    iv_display = f"{iv * 100:.1f}%" if iv is not None else "—"

    days_to_earnings = get_days_to_earnings(ticker)
    m1, m2 = st.columns(2)
    m1.metric("IV (current)", iv_display)
    m2.metric("Earnings in", f"{days_to_earnings}d" if days_to_earnings is not None else "—")

    # --- Greeks: net position (long leg minus short leg), each leg using its own IV ---
    spread_greeks = None
    if spot_price is not None:
        long_iv = long_leg.get("impliedVolatility")
        short_iv = short_leg.get("impliedVolatility")
        if long_iv is not None and short_iv is not None:
            long_greeks = compute_leg_greeks(option_type, spot_price, long_strike, expiry, risk_free_rate, long_iv)
            short_greeks = compute_leg_greeks(option_type, spot_price, short_strike, expiry, risk_free_rate, short_iv)
            spread_greeks = compute_spread_greeks(long_greeks, short_greeks)

            g1, g2, g3, g4 = st.columns(4)
            g1.metric("Delta", f"{spread_greeks['delta']:.3f}")
            g2.metric("Gamma", f"{spread_greeks['gamma']:.3f}")
            g3.metric("Theta", f"{spread_greeks['theta']:.3f}")
            g4.metric("Vega", f"{spread_greeks['vega']:.3f}")

    # --- log this view to the daily snapshot sheet, only if this is you ---
    if is_owner and breakevens is not None and max_pl is not None:
        try:
            greeks_kwargs = spread_greeks or {}
            logged = log_snapshot_if_new(
                ticker=ticker, expiry=expiry, option_type=option_type,
                long_strike=long_strike, short_strike=short_strike,
                iv=iv, spot_price=spot_price,
                breakeven=breakevens, max_profit=max_pl["max_profit"], max_loss=max_pl["max_loss"],
                days_to_earnings=days_to_earnings, vix=vix,
                delta=greeks_kwargs.get("delta"), gamma=greeks_kwargs.get("gamma"),
                theta=greeks_kwargs.get("theta"), vega=greeks_kwargs.get("vega"),
            )
            if logged:
                st.caption("📝 Logged today's snapshot for this spread.")
        except Exception as e:
            st.caption(f"⚠️ Couldn't log to Sheets: {e}")


cols = st.columns(num_tickers)
for col, ticker in zip(cols, tickers):
    with col:
        if ticker:
            render_ticker_panel(ticker.upper())
