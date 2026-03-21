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

# Strategy 5 — ETF master list (exact tickers from your Google Sheet col G rows 10-22)
STRATEGY5_ETF_MASTER = [
    {"Company Name": "NIFTY 50 ETF",                                    "Ticker symbols": "NIFTY_50",    "Category": "Core ETF"},
    {"Company Name": "NIFTY Next 50 ETF",                               "Ticker symbols": "JUNIORBEES",  "Category": "Core ETF"},
    {"Company Name": "SBI Nifty 50 ETF",                                "Ticker symbols": "SETFNIF50",   "Category": "Core ETF"},
    {"Company Name": "Nippon India Nifty ETF",                          "Ticker symbols": "NIFTYBEES",   "Category": "Core ETF"},
    {"Company Name": "Motilal Oswal Nasdaq 100 ETF",                    "Ticker symbols": "MON100",      "Category": "International ETF"},
    {"Company Name": "Motilal Oswal S&P 500 ETF",                       "Ticker symbols": "MASP500",     "Category": "International ETF"},
    {"Company Name": "NIFTY Bank ETF",                                  "Ticker symbols": "BANKBEES",    "Category": "Sector ETF"},
    {"Company Name": "NIFTY Auto ETF",                                  "Ticker symbols": "AUTOBEES",    "Category": "Sector ETF"},
    {"Company Name": "NiFTY Realty ETF",                                "Ticker symbols": "NIFTY_REALTY","Category": "Sector ETF"},
    {"Company Name": "Nippon NIFTY Infrastructure ETF",                 "Ticker symbols": "INFRABEES",   "Category": "Sector ETF"},
    {"Company Name": "Global X Artificial Intelligence & Technology ETF","Ticker symbols": "AIQ",         "Category": "Thematic ETF"},
    {"Company Name": "First Trust Nasdaq AI & Robotics ETF",            "Ticker symbols": "ROBT",        "Category": "Thematic ETF"},
    {"Company Name": "Global X Data Center & Digital Infrastructure ETF","Ticker symbols": "DTCR",        "Category": "Thematic ETF"},
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
        # Use get_all_values() to handle duplicate column headers in the sheet
        all_values = ws.get_all_values()
        if not all_values:
            raise RuntimeError("Worksheet is empty.")

        # Build unique headers: duplicate names get _2, _3 suffix
        raw_headers = all_values[0]
        seen = {}
        headers = []
        for h in raw_headers:
            h = h.strip()
            if h in seen:
                seen[h] += 1
                headers.append(f"{h}_{seen[h]}")
            else:
                seen[h] = 1
                headers.append(h)

        df = pd.DataFrame(all_values[1:], columns=headers)
        # Drop completely empty rows
        df = df[df.apply(lambda r: r.str.strip().ne("").any(), axis=1)].reset_index(drop=True)
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
    """
    Read ETFs from Stock Summary sheet — column A (name) and G (NSE Ticker).
    Reads ALL rows from row 10 downward until empty — no hardcoded row limit.
    Falls back to Strategy 5 master list if fetch fails.
    """
    log.info(f"Fetching ETF list from '{WORKSHEET_ETFS}' (row 10 onwards, no row limit) ...")
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_json = None
        try:
            import streamlit as st
            val = st.secrets.get("GOOGLE_SHEETS_CREDENTIALS")
            if val:
                creds_json = str(val)
        except Exception:
            pass
        if not creds_json:
            creds_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
        if not creds_json:
            log.warning("No credentials — using Strategy 5 master list for ETFs.")
            return None

        creds_info = json.loads(creds_json)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        ws = sh.worksheet(WORKSHEET_ETFS)

        # Read ALL values from col A and col G starting at row 10
        # No hardcoded upper limit — picks up any new ETFs added below row 22
        names   = ws.col_values(1)    # col A — all rows
        tickers = ws.col_values(7)    # col G — all rows

        # Pad shorter list to match length
        max_len = max(len(names), len(tickers))
        names   = names   + [""] * (max_len - len(names))
        tickers = tickers + [""] * (max_len - len(tickers))

        # Start from row 10 (index 9) — skip header rows above
        HEADER_SKIP = 9
        names   = names[HEADER_SKIP:]
        tickers = tickers[HEADER_SKIP:]

        # Skip known header/label rows
        SKIP_VALUES = {"", "nan", "none", "nse ticker", "ticker", "symbol",
                       "ticker symbols", "company name", "name"}

        rows = []
        for name, ticker in zip(names, tickers):
            name   = str(name).strip()
            ticker = str(ticker).strip().upper()
            if (name and ticker and
                name.lower()   not in SKIP_VALUES and
                ticker.lower() not in SKIP_VALUES):
                rows.append({
                    "Company Name":   name,
                    "Ticker symbols": ticker,
                    "Category":       "ETF",
                    "_source":        "google_sheet",
                })

        if rows:
            df = pd.DataFrame(rows)
            log.info(f"ETFs loaded from sheet: {len(df)} ETFs")
            log.info(f"  Tickers: {list(df['Ticker symbols'])}")
            return df
        else:
            log.warning("No ETF rows found in sheet — using master list.")
            return None

    except Exception as e:
        log.warning(f"ETF sheet fetch failed: {e} — using Strategy 5 master list.")
        return None


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
