"""
universe_loader.py
------------------
Fetches the user-maintained Google Sheet master list.
Uses Google Sheets API via service account (sheet is IIM-restricted, not public).
"""

import os
import io
import json
import logging
import requests
import pandas as pd
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("universe_loader")

SHEET_ID   = "1jTlHPIMOiXcCIFPlJcUS2NjtXh6iBdGBarO26glnFAk"

# ── Exact worksheet tab names from your Google Sheet ──────────────────────────
WORKSHEET_STOCKS = "Stock Fundamental"   # stocks tab
WORKSHEET_ETFS   = "Stock Summary"       # ETF tab

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Strategy 5 — fixed ETF master list (all NSE-listed)
STRATEGY5_ETF_MASTER = [
    {"Company Name": "Nifty 50 ETF (Nippon)",           "Ticker symbols": "NIFTYBEES",   "Category": "Core ETF"},
    {"Company Name": "Nifty Next 50 ETF (Nippon)",      "Ticker symbols": "JUNIORBEES",  "Category": "Core ETF"},
    {"Company Name": "SBI Nifty 50 ETF",                "Ticker symbols": "SETFNIF50",   "Category": "Core ETF"},
    {"Company Name": "Nippon India Nifty ETF",          "Ticker symbols": "NIPPONNIFTY", "Category": "Core ETF"},
    {"Company Name": "Motilal Oswal Nasdaq 100 ETF",    "Ticker symbols": "MOM100",      "Category": "International ETF"},
    {"Company Name": "Motilal Oswal S&P 500 ETF",       "Ticker symbols": "MAFANG",      "Category": "International ETF"},
    {"Company Name": "Nifty Bank ETF (ICICI)",          "Ticker symbols": "BANKBEES",    "Category": "Sector ETF"},
    {"Company Name": "Nifty Auto ETF",                  "Ticker symbols": "AUTOBEES",    "Category": "Sector ETF"},
    {"Company Name": "Nifty Realty ETF (Nippon)",       "Ticker symbols": "NIFTYREAL",   "Category": "Sector ETF"},
    {"Company Name": "Nippon Nifty Infrastructure ETF", "Ticker symbols": "INFRABEES",   "Category": "Sector ETF"},
    {"Company Name": "Global X AI & Technology ETF",    "Ticker symbols": "MOGLIXETF",   "Category": "Thematic ETF"},
    {"Company Name": "First Trust Nasdaq AI ETF",       "Ticker symbols": "AIIETF",      "Category": "Thematic ETF"},
    {"Company Name": "Global X Data Center ETF",        "Ticker symbols": "DCIETF",      "Category": "Thematic ETF"},
]


# ─────────────────────────────────────────────────────────────────────────────
# Ticker normalisation
# ─────────────────────────────────────────────────────────────────────────────

def normalise_ticker(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    t = raw.strip().upper().replace(" ", "").replace(".NS", "")
    if t in ("", "NOTEXISTS", "N/A", "NA", "NAN", "NONE", "-"):
        return None
    return f"{t}.NS"


# ─────────────────────────────────────────────────────────────────────────────
# Fetch via service account (primary method — sheet is private)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_via_service_account(worksheet_name: str) -> pd.DataFrame | None:
    import traceback
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as e:
        raise RuntimeError(f"Missing package: {e}. Run: pip install gspread google-auth")

    # ── Step 1: Get credentials JSON ─────────────────────────────────────────
    creds_json = None

    # Try st.secrets first
    try:
        import streamlit as st
        val = st.secrets.get("GOOGLE_SHEETS_CREDENTIALS")
        if val:
            creds_json = str(val)
            log.info("Credentials loaded from Streamlit secrets.")
    except Exception as e:
        log.info(f"Streamlit secrets not available: {e}")

    # Try os.environ
    if not creds_json:
        creds_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
        if creds_json:
            log.info("Credentials loaded from environment variable.")

    if not creds_json:
        raise RuntimeError(
            "GOOGLE_SHEETS_CREDENTIALS not found in Streamlit secrets or environment. "
            "Add it in Streamlit → App Settings → Secrets."
        )

    # ── Step 2: Parse JSON ────────────────────────────────────────────────────
    try:
        creds_info = json.loads(creds_json)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"GOOGLE_SHEETS_CREDENTIALS is not valid JSON: {e}")

    # ── Step 3: Authenticate ─────────────────────────────────────────────────
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        gc = gspread.authorize(creds)
    except Exception as e:
        raise RuntimeError(f"Google auth failed: {e}")

    # ── Step 4: Open sheet ───────────────────────────────────────────────────
    try:
        sh = gc.open_by_key(SHEET_ID)
    except Exception as e:
        raise RuntimeError(f"Cannot open sheet {SHEET_ID}: {e}. Check service account has Viewer access.")

    # ── Step 5: Open worksheet ───────────────────────────────────────────────
    try:
        ws = sh.worksheet(worksheet_name)
    except Exception as e:
        available = [w.title for w in sh.worksheets()]
        raise RuntimeError(f"Worksheet '{worksheet_name}' not found. Available: {available}")

    # ── Step 6: Fetch data ───────────────────────────────────────────────────
    try:
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        log.info(f"  → {len(df)} rows fetched from '{worksheet_name}'.")
        log.info(f"  Columns: {list(df.columns)}")
        return df
    except Exception as e:
        raise RuntimeError(f"Failed to read worksheet data: {e}")


def fetch_stock_universe() -> pd.DataFrame | None:
    """Fetch stocks directly via service account — sheet is IIM-restricted."""
    log.info(f"Fetching '{WORKSHEET_STOCKS}' via service account ...")
    return _fetch_via_service_account(WORKSHEET_STOCKS)


def fetch_etf_universe() -> pd.DataFrame | None:
    """Fetch ETFs directly via service account."""
    log.info(f"Fetching '{WORKSHEET_ETFS}' via service account ...")
    return _fetch_via_service_account(WORKSHEET_ETFS)


# ─────────────────────────────────────────────────────────────────────────────
# Processing
# ─────────────────────────────────────────────────────────────────────────────

def _find_ticker_column(df: pd.DataFrame) -> str | None:
    """Find ticker column regardless of exact name."""
    candidates = [
        "Ticker symbols", "Ticker (NSE)", "Ticker Symbol",
        "Ticker", "NSE Ticker", "Symbol", "NSE Symbol",
        "ticker", "TICKER", "Ticker symbols ",
    ]
    for c in candidates:
        if c in df.columns:
            return c
    # Partial match fallback
    for col in df.columns:
        if "ticker" in col.lower() or "symbol" in col.lower():
            return col
    return None


def process_stock_universe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    ticker_col = _find_ticker_column(df)
    if ticker_col is None:
        log.error(f"No ticker column found. Columns available: {list(df.columns)}")
        raise KeyError(f"No ticker column found. Columns: {list(df.columns)}")

    log.info(f"Using ticker column: '{ticker_col}'")
    df = df.rename(columns={ticker_col: "Ticker (NSE)"})

    # Rename other columns to standard names if needed
    for old, new in [("Name", "Company Name"), ("name", "Company Name")]:
        if old in df.columns and "Company Name" not in df.columns:
            df = df.rename(columns={old: "Company Name"})

    # Normalise tickers
    df["Ticker (NSE)"] = df["Ticker (NSE)"].apply(normalise_ticker)
    before = len(df)
    df = df[df["Ticker (NSE)"].notna()].reset_index(drop=True)
    skipped = before - len(df)
    if skipped:
        log.info(f"  Skipped {skipped} rows with invalid/missing tickers.")

    df["_fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log.info(f"Stock universe ready: {len(df)} stocks.")
    return df


def process_etf_universe(df: pd.DataFrame | None) -> pd.DataFrame:
    s5_df = pd.DataFrame(STRATEGY5_ETF_MASTER)
    s5_df["Ticker (NSE)"] = s5_df["Ticker symbols"].apply(
        lambda x: normalise_ticker(x) or x + ".NS"
    )
    s5_df["_source"] = "strategy5_master"

    if df is not None and len(df) > 0:
        ticker_col = _find_ticker_column(df)
        if ticker_col:
            df = df.rename(columns={ticker_col: "Ticker (NSE)"})
            df["Ticker (NSE)"] = df["Ticker (NSE)"].apply(normalise_ticker)
            df = df[df["Ticker (NSE)"].notna()].copy()
        df["_source"] = "google_sheet"
        sheet_tickers = set(df["Ticker (NSE)"].tolist()) if "Ticker (NSE)" in df.columns else set()
        extra_s5 = s5_df[~s5_df["Ticker (NSE)"].isin(sheet_tickers)]
        combined = pd.concat([df, extra_s5], ignore_index=True)
    else:
        log.warning("No ETF data from sheet — using Strategy 5 master list only.")
        combined = s5_df.copy()

    combined["_fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log.info(f"ETF universe ready: {len(combined)} ETFs.")
    return combined


# ─────────────────────────────────────────────────────────────────────────────
# Change detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_changes(current: pd.DataFrame, prev_path: Path) -> pd.DataFrame:
    changes = []
    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not prev_path.exists():
        return pd.DataFrame()

    try:
        prev = pd.read_csv(prev_path)
    except Exception:
        return pd.DataFrame()

    curr_tickers = set(current["Ticker (NSE)"].tolist())
    prev_tickers = set(prev["Ticker (NSE)"].tolist())

    for t in sorted(curr_tickers - prev_tickers):
        row = current[current["Ticker (NSE)"] == t].iloc[0]
        changes.append({"run_at": run_ts, "change_type": "ADDED", "ticker": t,
            "company": row.get("Company Name", ""),
            "detail": f"Added | TA Status: {row.get('TA Status', '')}"})

    for t in sorted(prev_tickers - curr_tickers):
        row = prev[prev["Ticker (NSE)"] == t].iloc[0]
        changes.append({"run_at": run_ts, "change_type": "REMOVED", "ticker": t,
            "company": row.get("Company Name", ""),
            "detail": f"Removed | Was TA Status: {row.get('TA Status', '')}"})

    curr_idx = current.set_index("Ticker (NSE)")
    prev_idx = prev.set_index("Ticker (NSE)")
    for t in sorted(curr_tickers & prev_tickers):
        try:
            cs = str(curr_idx.loc[t, "TA Status"]).strip() if "TA Status" in curr_idx.columns else ""
            ps = str(prev_idx.loc[t, "TA Status"]).strip() if "TA Status" in prev_idx.columns else ""
            if cs != ps:
                changes.append({"run_at": run_ts, "change_type": "TA_STATUS_CHANGED",
                    "ticker": t, "company": curr_idx.loc[t, "Company Name"] if "Company Name" in curr_idx.columns else "",
                    "detail": f"TA Status: '{ps}' → '{cs}'"})
        except Exception:
            pass

    log.info(f"Changes detected: {len(changes)}" if changes else "No changes detected.")
    return pd.DataFrame(changes)


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def run() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    stock_path      = DATA_DIR / "stock_universe.csv"
    etf_path        = DATA_DIR / "etf_universe.csv"
    prev_stock_path = DATA_DIR / "stock_universe_prev.csv"
    changes_path    = DATA_DIR / "universe_changes.csv"

    if stock_path.exists():
        import shutil
        shutil.copy(stock_path, prev_stock_path)

    raw_stocks = fetch_stock_universe()
    raw_etfs   = fetch_etf_universe()

    if raw_stocks is None:
        raise  # re-raise the actual error so dashboard shows real message

    stocks = process_stock_universe(raw_stocks)
    etfs   = process_etf_universe(raw_etfs)

    changes = detect_changes(stocks, prev_stock_path)
    if not changes.empty:
        if changes_path.exists():
            existing = pd.read_csv(changes_path)
            changes = pd.concat([existing, changes], ignore_index=True)
        changes.to_csv(changes_path, index=False)

    stocks.to_csv(stock_path, index=False)
    etfs.to_csv(etf_path, index=False)
    log.info(f"Saved: {len(stocks)} stocks, {len(etfs)} ETFs")

    return {
        "stock_count":   len(stocks),
        "etf_count":     len(etfs),
        "stock_tickers": stocks["Ticker (NSE)"].tolist(),
        "etf_tickers":   etfs["Ticker (NSE)"].tolist(),
        "changes_count": len(changes) if not changes.empty else 0,
        "fetched_at":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


if __name__ == "__main__":
    result = run()
    print(f"\nStocks: {result['stock_count']}  ETFs: {result['etf_count']}")
