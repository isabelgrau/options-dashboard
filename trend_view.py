"""
Trend view (beta) — the actual payoff of the daily snapshot logger.
Rough first pass: testing the "today card + pick-a-metric" design against
real logged data (MSFT's 500/525 spread has entries on Aug 4, 7, and 10 —
enough to sanity-check the design, not enough yet to trust the shape of
any real trend). Revisit once a tracked position has ~2 weeks of daily
history behind it.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from sheets_log import get_logged_positions, get_position_history, get_active_position_keys

METRIC_OPTIONS = {
    "IV": "iv",
    "Delta": "delta",
    "Gamma": "gamma",
    "Theta": "theta",
    "Vega": "vega",
    "Spot price": "spot_price",
}


def render_trend_view():
    st.subheader("Trend view (beta)")
    st.caption("Prototype — checking the design against real logged data before committing to it.")

    positions = get_logged_positions()
    if not positions:
        st.info("No logged positions yet — trend view has nothing to show until the log has data.")
        return

    active_keys = get_active_position_keys()
    positions = [
        p for p in positions
        if (str(p[0]).strip().upper(), str(p[1]).strip(), str(p[2]).strip().lower(), float(p[3]), float(p[4])) in active_keys
    ]
    if not positions:
        st.info("No active tracked positions yet — add one to tracked_positions to see it here.")
        return

    positions = sorted(positions)  # ticker, then expiry (ISO dates sort chronologically), then strikes
    labels = [f"{t} {e} {ot} {ls:.0f}/{ss:.0f}" for t, e, ot, ls, ss in positions]
    choice = st.selectbox("Position", labels)
    ticker, expiry, option_type, long_strike, short_strike = positions[labels.index(choice)]

    history = get_position_history(ticker, expiry, option_type, long_strike, short_strike)
    if not history:
        st.info("No history for this position yet.")
        return

    df = pd.DataFrame(history)
    df["date"] = pd.to_datetime(df["date"])

    # --- today card: most recent logged row ---
    latest = df.iloc[-1]
    st.caption(f"Latest snapshot: {latest['date'].date()}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Spot", f"{float(latest.get('spot_price') or 0):.2f}")
    iv_val = latest.get("iv")
    c2.metric("IV", f"{float(iv_val) * 100:.1f}%" if iv_val not in (None, "") else "—")
    c3.metric("Delta", f"{float(latest.get('delta') or 0):.3f}")
    c4.metric("Breakeven", f"{float(latest.get('breakeven') or 0):.2f}")

    # --- pick-a-metric trend chart ---
    metric_label = st.selectbox("Look back — pick a metric", list(METRIC_OPTIONS.keys()))
    metric_col = METRIC_OPTIONS[metric_label]

    # Reindex to every calendar day in range so real gaps render as visible
    # breaks in the line, rather than silently connecting Aug 4 to Aug 7
    # as if nothing happened in between.
    full_range = pd.date_range(df["date"].min(), df["date"].max(), freq="D")
    series = df.set_index("date")[metric_col].apply(pd.to_numeric, errors="coerce")
    series = series.reindex(full_range)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=series.index, y=series.values, mode="lines+markers", connectgaps=False
    ))
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"{len(df)} days logged for this position · gaps shown as breaks in the line")
