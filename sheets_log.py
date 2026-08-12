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
from datetime import datetime
from zoneinfo import ZoneInfo

SHEET_NAME = "Options Dashboard Log"   # must match your actual Google Sheet's title exactly
WORKSHEET_NAME = "log"                 # the tab within that Sheet
CREDENTIALS_PATH = "credentials.json"  # local-dev fallback only; see _get_client


def _today_et() -> str:
    """
    Today's date per US Eastern time, not the machine's local clock.
    Matters because this can run inside GitHub Actions (UTC) — UTC's date
    rolls over at 7-8pm Eastern, not near Eastern midnight, so a naive
    date.today() could silently log tomorrow's date for part of the evening.
    """
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()

COLUMNS = [
    "date", "ticker", "expiry", "option_type",
    "long_strike", "short_strike",
    "iv", "spot_price", "breakeven", "max_profit", "max_loss",
    "days_to_earnings", "vix",
    "delta", "gamma", "theta", "vega",
    "iv_rank_manual", "iv_percentile_manual", "iv_hv_ratio_manual",  # fill in by hand
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
    today_str = _today_et()
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
    delta: float | None = None, gamma: float | None = None,
    theta: float | None = None, vega: float | None = None,
) -> bool:
    """
    Appends a row if this exact spread config hasn't been logged today.
    Returns True if a new row was written, False if already logged.

    Row-building is header-driven: we read the sheet's actual header row
    and match field names to it, rather than assuming a fixed column
    order. This means adding, removing, or reordering columns in Sheets
    (like your manual iv_rank/iv_percentile/iv_hv_ratio columns) never
    requires a code change — any header we don't have a value for is
    just left blank automatically.
    """
    key = (ticker, expiry, option_type, float(long_strike), float(short_strike))
    if key in _existing_keys_today():
        return False

    ws = _get_worksheet()
    header = ws.row_values(1)

    data = {
        "date": _today_et(),
        "ticker": ticker, "expiry": expiry, "option_type": option_type,
        "long_strike": long_strike, "short_strike": short_strike,
        "iv": iv, "spot_price": spot_price,
        "breakeven": breakeven, "max_profit": max_profit, "max_loss": max_loss,
        "days_to_earnings": days_to_earnings, "vix": vix,
        "delta": delta, "gamma": gamma, "theta": theta, "vega": vega,
    }
    row = [data.get(col, "") for col in header]

    # Explicit row targeting instead of append_row()'s automatic table-range
    # detection — that auto-detection can misfire when other columns (like
    # your dte formula) have values filled further down than the real data,
    # making Sheets misjudge where the table actually ends. Column A ("date")
    # is fully controlled by this script and never touched by your formulas,
    # so counting it directly gives a reliable next-row position.
    next_row = len(ws.col_values(1)) + 1
    ws.update(f"A{next_row}", [row], value_input_option="RAW")
    _existing_keys_today.clear()  # invalidate cache so this write is reflected immediately
    return True


# ============================================================
# Watchlist: ticker-level tracking, no position attached.
# Separate from the spread-level log above on purpose — a watchlist
# entry isn't a position, and mixing the two schemas (strikes vs. no
# strikes) would make later analysis messier, not simpler.
# ============================================================

WATCHLIST_TAB_NAME = "watchlist"              # you maintain this: just a list of tickers
WATCHLIST_LOG_TAB_NAME = "watchlist_log"       # auto-created on first write, like the main log
WATCHLIST_LOG_COLUMNS = ["date", "ticker", "spot_price", "atm_iv", "atm_expiry", "vix"]


def get_watchlist_tickers() -> list:
    """Reads the 'watchlist' tab — expects a 'ticker' column, one ticker per row."""
    client = _get_client()
    sheet = client.open(SHEET_NAME)
    ws = sheet.worksheet(WATCHLIST_TAB_NAME)
    records = ws.get_all_records()
    return [str(r["ticker"]).strip().upper() for r in records if r.get("ticker")]


@st.cache_resource
def _get_watchlist_log_worksheet():
    client = _get_client()
    sheet = client.open(SHEET_NAME)
    try:
        ws = sheet.worksheet(WATCHLIST_LOG_TAB_NAME)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=WATCHLIST_LOG_TAB_NAME, rows=1000, cols=len(WATCHLIST_LOG_COLUMNS))
        ws.append_row(WATCHLIST_LOG_COLUMNS)
    return ws


@st.cache_data(ttl=300)
def _existing_watchlist_keys_today() -> set:
    ws = _get_watchlist_log_worksheet()
    records = ws.get_all_records()
    today_str = _today_et()
    return {row.get("ticker") for row in records if row.get("date") == today_str}


def log_watchlist_snapshot_if_new(ticker: str, spot_price, atm_iv, atm_expiry, vix) -> bool:
    """Same dedup pattern as the main log, keyed by ticker + date only (no strikes involved)."""
    if ticker in _existing_watchlist_keys_today():
        return False

    ws = _get_watchlist_log_worksheet()
    header = ws.row_values(1)
    data = {
        "date": _today_et(), "ticker": ticker,
        "spot_price": spot_price, "atm_iv": atm_iv, "atm_expiry": atm_expiry, "vix": vix,
    }
    row = [data.get(col, "") for col in header]
    next_row = len(ws.col_values(1)) + 1
    ws.update(f"A{next_row}", [row], value_input_option="RAW")
    _existing_watchlist_keys_today.clear()
    return True
