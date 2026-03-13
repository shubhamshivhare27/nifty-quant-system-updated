"""
portfolio.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Syncs current Upstox portfolio holdings.
Uses upstox_auth.get_valid_token() — auto-refreshes if expired.

Provides:
  get_portfolio_details()   → full holdings DataFrame
  get_portfolio_tickers()   → set of SYMBOL.NS tickers currently held
  get_removed_tickers()     → held tickers NOT in current sheet
  save_portfolio_snapshot() → saves to data/portfolio_snapshot.csv
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import logging
import pandas as pd
from datetime import datetime
from pathlib import Path

log = logging.getLogger("portfolio")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def get_portfolio_details() -> pd.DataFrame:
    """
    Fetch current Upstox holdings via the portfolio API.
    Auto-refreshes access token if expired.

    Returns DataFrame: ticker, company_name, qty, avg_cost, ltp, pnl_inr, pnl_pct
    Raises ValueError with clear message on any failure.
    """
    import requests
    from src.upstox_auth import get_valid_token, is_connected

    # Check if OAuth is set up at all
    if not is_connected():
        raise ValueError(
            "Upstox is not connected. "
            "Go to the Portfolio page and click 'Connect Upstox' to complete the one-time login."
        )

    # Get valid token (auto-refreshes if needed)
    token = get_valid_token()

    try:
        url     = "https://api.upstox.com/v2/portfolio/long-term-holdings"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept":        "application/json",
        }
        resp = requests.get(url, headers=headers, timeout=30)

        if resp.status_code == 401:
            raise ValueError(
                "Upstox token is invalid or expired (401). "
                "The auto-refresh may have failed — try clicking 'Connect Upstox' again."
            )
        if resp.status_code == 403:
            raise ValueError(
                "Permission denied (403). "
                "Ensure your Upstox app has 'holdings' scope enabled."
            )
        if resp.status_code != 200:
            raise ValueError(f"Upstox API error {resp.status_code}: {resp.text[:300]}")

        data = resp.json().get("data", [])
        if not data:
            log.info("Upstox portfolio: no holdings found.")
            return pd.DataFrame()

        rows = []
        for item in data:
            symbol  = item.get("tradingsymbol", "")
            ticker  = f"{symbol}.NS" if not symbol.endswith(".NS") else symbol
            qty     = float(item.get("quantity", 0))
            avg     = float(item.get("average_price", 0))
            ltp     = float(item.get("last_price", 0))
            pnl     = round((ltp - avg) * qty, 2)
            pnl_pct = round((ltp - avg) / avg * 100, 2) if avg > 0 else 0.0

            rows.append({
                "ticker":        ticker,
                "company_name":  item.get("company_name", symbol),
                "qty":           qty,
                "avg_cost":      round(avg, 2),
                "ltp":           round(ltp, 2),
                "pnl_inr":       pnl,
                "pnl_pct":       pnl_pct,
                "isin":          item.get("isin", ""),
            })

        df = pd.DataFrame(rows)
        log.info(f"Portfolio synced: {len(df)} holdings.")
        return df

    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Portfolio sync failed: {e}") from e


def get_portfolio_tickers() -> set:
    """Returns set of SYMBOL.NS tickers currently held."""
    try:
        df = get_portfolio_details()
        return set(df["ticker"].tolist()) if not df.empty else set()
    except Exception:
        return set()


def get_removed_tickers(sheet_tickers: set) -> set:
    """
    Returns tickers held in Upstox that have been removed from the Google Sheet.
    These still need EXIT signal evaluation (Holding Protection Rule).
    """
    portfolio = get_portfolio_tickers()
    removed   = portfolio - sheet_tickers
    if removed:
        log.warning(f"Holdings removed from sheet: {removed}")
    return removed


def save_portfolio_snapshot(df: pd.DataFrame) -> None:
    """Save portfolio snapshot to data/portfolio_snapshot.csv."""
    if df.empty:
        return
    path = DATA_DIR / "portfolio_snapshot.csv"
    df["snapshot_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df.to_csv(path, index=False)
    log.info(f"Portfolio snapshot saved → {path}")
