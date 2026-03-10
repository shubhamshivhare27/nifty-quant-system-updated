"""
portfolio.py
------------
Syncs current Upstox portfolio holdings.

Provides:
  - get_portfolio_tickers()    → set of SYMBOL.NS tickers currently held
  - get_removed_tickers()      → tickers in portfolio but NOT in current sheet
  - get_portfolio_details()    → full holdings with qty, avg_cost, current price, P&L
"""

import os
import logging
import requests
import pandas as pd
from datetime import datetime
from pathlib import Path

log = logging.getLogger("portfolio")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _get_upstox_token() -> str | None:
    token = os.environ.get("UPSTOX_TOKEN", "").strip()
    return token if token else None


def get_portfolio_details() -> pd.DataFrame:
    """
    Fetch current Upstox holdings via the portfolio API.
    Returns DataFrame with: ticker, company_name, qty, avg_cost, ltp, pnl, pnl_pct, days_held

    Falls back to empty DataFrame on failure (graceful degradation).
    """
    token = _get_upstox_token()
    if not token:
        log.warning("No UPSTOX_TOKEN — returning empty portfolio.")
        return pd.DataFrame()

    try:
        url = "https://api.upstox.com/v2/portfolio/long-term-holdings"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            log.warning(f"Upstox portfolio API returned {resp.status_code}: {resp.text[:200]}")
            return pd.DataFrame()

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
            pnl     = (ltp - avg) * qty
            pnl_pct = ((ltp - avg) / avg * 100) if avg > 0 else 0

            rows.append({
                "ticker":       ticker,
                "company_name": item.get("company_name", symbol),
                "qty":          qty,
                "avg_cost":     round(avg, 2),
                "ltp":          round(ltp, 2),
                "pnl_inr":      round(pnl, 2),
                "pnl_pct":      round(pnl_pct, 2),
                "isin":         item.get("isin", ""),
            })

        df = pd.DataFrame(rows)
        log.info(f"Portfolio synced: {len(df)} holdings.")
        return df

    except Exception as e:
        log.error(f"Portfolio sync failed: {e}", exc_info=True)
        return pd.DataFrame()


def get_portfolio_tickers() -> set[str]:
    """Returns set of SYMBOL.NS tickers currently held in Upstox."""
    df = get_portfolio_details()
    if df.empty:
        return set()
    return set(df["ticker"].tolist())


def get_removed_tickers(sheet_tickers: set[str]) -> set[str]:
    """
    Returns tickers that are currently held in Upstox portfolio
    but have been REMOVED from the Google Sheet master list.

    These must still be evaluated for EXIT signals (Holding Protection Rule).
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
