"""
Scheduled daily snapshot — run by GitHub Actions, not the Streamlit app.
Logs every position in the `tracked_positions` sheet tab (status=active),
independent of whether you ever open the dashboard that day.

Runs ALONGSIDE the app's log-on-view logging, not instead of it — ad-hoc
tickers you're just browsing still get captured when you view them; this
script's job is only to make sure your actively-tracked positions never
have a gap just because you didn't open the app.

Reuses the exact same fetch/compute/log functions as app.py, so the two
logging paths can't silently drift out of sync with each other.
"""

from options_data import (
    get_leg_quote,
    fetch_current_price,
    fetch_vix,
    fetch_risk_free_rate,
    get_days_to_earnings,
    get_nearest_atm_iv,
)
from analytics import compute_breakevens, compute_max_profit_loss
from greeks import compute_leg_greeks, compute_spread_greeks
from sheets_log import (
    log_snapshot_if_new, _get_client, SHEET_NAME,
    get_watchlist_tickers, log_watchlist_snapshot_if_new,
)

TRACKED_WORKSHEET_NAME = "tracked_positions"


def get_tracked_positions() -> list[dict]:
    """Active rows only — status must be exactly 'active' (case-insensitive)."""
    client = _get_client()
    sheet = client.open(SHEET_NAME)
    ws = sheet.worksheet(TRACKED_WORKSHEET_NAME)
    records = ws.get_all_records()
    active, skipped = [], []
    for r in records:
        if str(r.get("status", "")).strip().lower() == "active":
            active.append(r)
        else:
            skipped.append(r)
    for r in skipped:
        print(f"SKIP (status={r.get('status')!r})  {r.get('ticker')} {r.get('expiry')} "
              f"{r.get('long_strike')}/{r.get('short_strike')}")
    return active


def log_position(pos: dict, vix: float, risk_free_rate: float):
    ticker = str(pos["ticker"]).strip().upper()
    expiry = str(pos["expiry"]).strip()
    option_type = str(pos["option_type"]).strip().lower()
    long_strike = float(pos["long_strike"])
    short_strike = float(pos["short_strike"])

    long_leg = get_leg_quote(ticker, expiry, long_strike, option_type)
    short_leg = get_leg_quote(ticker, expiry, short_strike, option_type)
    if long_leg is None or short_leg is None:
        print(f"SKIP  {ticker} {expiry} {long_strike}/{short_strike} — strikes not found in chain (expired? typo?)")
        return

    long_price = long_leg["lastPrice"]
    short_price = short_leg["lastPrice"]
    iv = long_leg.get("impliedVolatility")
    spot_price = fetch_current_price(ticker)

    breakeven = compute_breakevens(long_strike, long_price, short_strike, short_price, option_type)
    max_pl = compute_max_profit_loss(long_strike, long_price, short_strike, short_price, option_type)
    days_to_earnings = get_days_to_earnings(ticker)

    spread_greeks = {}
    long_iv = long_leg.get("impliedVolatility")
    short_iv = short_leg.get("impliedVolatility")
    if spot_price is not None and long_iv is not None and short_iv is not None:
        long_greeks = compute_leg_greeks(option_type, spot_price, long_strike, expiry, risk_free_rate, long_iv)
        short_greeks = compute_leg_greeks(option_type, spot_price, short_strike, expiry, risk_free_rate, short_iv)
        spread_greeks = compute_spread_greeks(long_greeks, short_greeks)

    logged = log_snapshot_if_new(
        ticker=ticker, expiry=expiry, option_type=option_type,
        long_strike=long_strike, short_strike=short_strike,
        iv=iv, spot_price=spot_price,
        breakeven=breakeven, max_profit=max_pl["max_profit"], max_loss=max_pl["max_loss"],
        days_to_earnings=days_to_earnings, vix=vix,
        delta=spread_greeks.get("delta"), gamma=spread_greeks.get("gamma"),
        theta=spread_greeks.get("theta"), vega=spread_greeks.get("vega"),
    )
    status = "LOGGED" if logged else "ALREADY LOGGED"
    iv_str = f"{iv * 100:.1f}%" if iv is not None else "—"
    delta_str = f"{spread_greeks.get('delta'):.3f}" if spread_greeks.get("delta") is not None else "—"
    print(
        f"{status}  {ticker} {expiry} {long_strike}/{short_strike}  "
        f"| IV {iv_str}  delta {delta_str}  breakeven {breakeven:.2f}"
    )


def log_watchlist(vix: float):
    tickers = get_watchlist_tickers()
    if not tickers:
        print("No watchlist tickers found — nothing to log for watchlist.")
        return
    for ticker in tickers:
        spot_price = fetch_current_price(ticker)
        if spot_price is None:
            print(f"SKIP (watchlist)  {ticker} — couldn't get spot price")
            continue
        atm_iv, atm_expiry = get_nearest_atm_iv(ticker, spot_price)
        logged = log_watchlist_snapshot_if_new(ticker, spot_price, atm_iv, atm_expiry, vix)
        iv_str = f"{atm_iv * 100:.1f}%" if atm_iv is not None else "—"
        status = "LOGGED" if logged else "ALREADY LOGGED"
        print(f"{status} (watchlist)  {ticker}  | spot {spot_price:.2f}  ATM IV {iv_str} ({atm_expiry})")


def main():
    client = _get_client()
    resolved_sheet = client.open(SHEET_NAME)
    print(f"Resolved spreadsheet: '{resolved_sheet.title}'  ({resolved_sheet.url})")

    vix = fetch_vix()
    risk_free_rate = fetch_risk_free_rate()

    positions = get_tracked_positions()
    if not positions:
        print("No active tracked positions found — nothing to log for positions.")
    for pos in positions:
        try:
            log_position(pos, vix, risk_free_rate)
        except Exception as e:
            # One bad row (typo, delisted ticker) shouldn't kill the whole run.
            print(f"ERROR logging {pos}: {e}")

    # Watchlist logging paused (2026-08-09) — atm_iv proxy confirmed unreliable
    # (single-expiry, no interpolation) vs. IBKR's real V30 methodology.
    # log_watchlist() left intact below in case this gets revisited later.
    # log_watchlist(vix)


if __name__ == "__main__":
    main()
