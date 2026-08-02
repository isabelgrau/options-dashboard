"""
Daily snapshot logger — appends one row per unique spread configuration
viewed, per day, to a Google Sheet. Triggered inline whenever that config
is viewed in the app (see render_ticker_panel in app.py) — no scheduled
job, no cron. Viewing a ticker/strike combo IS what starts its log.

Design choice (v2, "Option 1"): every unique combo you view gets logged,
with no filtering for "which one is my real position." Simpler, no manual
marker to remember. Revisit if the noise ever becomes annoying in practice.
"""

import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import date

SHEET_NAME = "options_dashboard_log"   # rename to match your actual Google Sheet's name
WORKSHEET_NAME = "log"                 # the tab within that Sheet
CREDENTIALS_PATH = "credentials.json"  # local-dev fallback only; see _get_client

COLUMNS = [
    "date", "ticker", "expiry", "option_type",
    "long_strike", "short_strike",
    "iv", "spot_price", "breakeven", "max_profit", "max_loss",
    "days_to_earnings", "vix",
    "iv_rank_manual",  # left blank on write — fill in by hand from IBKR desktop
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_client():
    """
    Auth works two ways so the same code runs locally and on Streamlit Cloud:
      - Deployed: reads credentials from Streamlit Secrets (st.secrets["gcp_service_account"])
      - Local: falls back to a JSON key file on disk (CREDENTIALS_PATH)
    """
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
    return gspread.authorize(creds)


@st.cache_resource
def _get_worksheet():
    """Cached connection — avoids re-authenticating on every Streamlit rerun."""
    client = _get_client()
    sheet = client.open(SHEET_NAME)
    try:
        ws = sheet.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=len(COLUMNS))
        ws.append_row(COLUMNS)
    return ws


@st.cache_data(ttl=300)  # 5 min — avoids re-reading the whole sheet on every rerun
def _existing_keys_today() -> set:
    """
    Returns the set of (ticker, expiry, option_type, long_strike, short_strike)
    combos already logged today, so repeated views don't write duplicates.
    """
    ws = _get_worksheet()
    records = ws.get_all_records()
    today_str = date.today().isoformat()
    keys = set()
    for row in records:
        if row.get("date") == today_str:
            keys.add((
                row.get("ticker"), row.get("expiry"), row.get("option_type"),
                float(row.get("long_strike", 0)), float(row.get("short_strike", 0)),
            ))
    return keys


def log_snapshot_if_new(
    ticker: str, expiry: str, option_type: str,
    long_strike: float, short_strike: float,
    iv: float | None, spot_price: float | None,
    breakeven: float | None, max_profit: float | None, max_loss: float | None,
    days_to_earnings: int | None, vix: float | None,
) -> bool:
    """
    Appends a row if this exact spread config hasn't been logged today.
    Returns True if a new row was written, False if already logged.
    """
    key = (ticker, expiry, option_type, float(long_strike), float(short_strike))
    if key in _existing_keys_today():
        return False

    ws = _get_worksheet()
    row = [
        date.today().isoformat(), ticker, expiry, option_type,
        long_strike, short_strike,
        iv, spot_price, breakeven, max_profit, max_loss,
        days_to_earnings, vix,
        "",  # iv_rank_manual — fill in by hand
    ]
    ws.append_row(row)
    _existing_keys_today.clear()  # invalidate cache so this write is reflected immediately
    return True
