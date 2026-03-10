"""
universe_loader.py
------------------
Fetches the user-maintained Google Sheet master list.
- Primary:  public CSV export (no auth required)
- Fallback: Google Sheets API v4 via service account (gspread)

Saves:
  data/stock_universe.csv       — from "Stock Fundamentals" worksheet
  data/etf_universe.csv         — from "Stock Summary" worksheet
  data/stock_universe_prev.csv  — previous run's copy (for change detection)
  data/universe_changes.csv     — additions / removals / TA-status changes

ETF master list for Strategy 5 is hard-coded here and merged with
whatever is in the "Stock Summary" worksheet.
"""

import os
import io
import json
import logging
import requests
import pandas as pd
from datetime import datetime
from pathlib import Path

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("universe_loader")

# ── constants ─────────────────────────────────────────────────────────────────
SHEET_ID = "1jTlHPIMOiXcCIFPlJcUS2NjtXh6iBdGBarO26glnFAk"
GID_STOCKS = "1666453875"       # "Stock Fundamentals"
GID_ETFS   = "0"                # "Stock Summary" (default gid — adjust if different)

PUBLIC_CSV_URL_STOCKS = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
    f"/export?format=csv&gid={GID_STOCKS}"
)
PUBLIC_CSV_URL_ETFS = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
    f"/export?format=csv&gid={GID_ETFS}"
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Strategy 5 — fixed ETF master list (all listed on NSE, fetched via Upstox)
STRATEGY5_ETF_MASTER = [
    {"Company Name": "Nifty 50 ETF (Nippon)",          "Ticker (NSE)": "NIFTYBEES",  "Category": "Core ETF"},
    {"Company Name": "Nifty Next 50 ETF (Nippon)",     "Ticker (NSE)": "JUNIORBEES", "Category": "Core ETF"},
    {"Company Name": "SBI Nifty 50 ETF",               "Ticker (NSE)": "SETFNIF50",  "Category": "Core ETF"},
    {"Company Name": "Nippon India Nifty ETF",         "Ticker (NSE)": "NIPPONNIFTY","Category": "Core ETF"},
    {"Company Name": "Motilal Oswal Nasdaq 100 ETF",   "Ticker (NSE)": "MOM100",     "Category": "International ETF"},
    {"Company Name": "Motilal Oswal S&P 500 ETF",      "Ticker (NSE)": "MAFANG",     "Category": "International ETF"},
    {"Company Name": "Nifty Bank ETF (ICICI)",         "Ticker (NSE)": "BANKBEES",   "Category": "Sector ETF"},
    {"Company Name": "Nifty Auto ETF",                 "Ticker (NSE)": "AUTOBEES",   "Category": "Sector ETF"},
    {"Company Name": "Nifty Realty ETF (Nippon)",      "Ticker (NSE)": "NIFTYREAL",  "Category": "Sector ETF"},
    {"Company Name": "Nippon Nifty Infrastructure ETF","Ticker (NSE)": "INFRABEES",  "Category": "Sector ETF"},
    {"Company Name": "Global X AI & Technology ETF",   "Ticker (NSE)": "MOGLIXETF",  "Category": "Thematic ETF"},
    {"Company Name": "First Trust Nasdaq AI ETF",      "Ticker (NSE)": "AIIETF",     "Category": "Thematic ETF"},
    {"Company Name": "Global X Data Center ETF",       "Ticker (NSE)": "DCIETF",     "Category": "Thematic ETF"},
]

# Columns expected from "Stock Fundamentals" worksheet
STOCK_COLUMNS = [
    "S.No.", "Company Name", "TA - SSF", "TA - MACD", "TA - RSI", "TA Status",
    "CMP (Rs.)", "P/E", "Market Cap (Rs. Cr.)", "Div Yield %",
    "NP Qtr (Rs. Cr.)", "Qtr Profit Var %", "Sales Qtr (Rs. Cr.)", "Qtr Sales Var %",
    "ROCE %", "EPS Ann (Rs.)", "EPS Var 5Yrs %", "Ticker (NSE)",
    "Rev Analysts", "Rev Avg Est (INR Mn)", "Rev Growth %",
    "EPS Analysts", "EPS Avg Est", "EPS Growth %",
    "Price High", "High % Change", "Price Avg", "Avg % Change",
    "Price Low", "Low % Change", "Price Analysts",
    "F-Score", "Z-Score", "M-Score",
]


# ─────────────────────────────────────────────────────────────────────────────
# Ticker normalisation
# ─────────────────────────────────────────────────────────────────────────────

def normalise_ticker(raw: str) -> str | None:
    """
    'ITC'      → 'ITC.NS'
    'ITC.NS'   → 'ITC.NS'
    'Not Exists' / '' / 'N/A' → None  (skip row)
    """
    if not isinstance(raw, str):
        return None
    t = raw.strip().upper().replace(" ", "").replace(".NS", "")
    if t in ("", "NOTEXISTS", "N/A", "NA", "NAN", "NONE", "-"):
        return None
    return f"{t}.NS"


# ─────────────────────────────────────────────────────────────────────────────
# Sheet fetching
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_csv_public(url: str) -> pd.DataFrame | None:
    """Try the public CSV export. Returns None if sheet is private or on error."""
    try:
        log.info(f"Trying public CSV export: {url}")
        resp = requests.get(url, timeout=30)
        if "<html" in resp.text[:200].lower():
            log.warning("Sheet is private — public CSV export rejected.")
            return None
        df = pd.read_csv(io.StringIO(resp.text))
        log.info(f"  → {len(df)} rows fetched via public CSV.")
        return df
    except Exception as e:
        log.warning(f"Public CSV fetch failed: {e}")
        return None


def _fetch_csv_service_account(worksheet_name: str) -> pd.DataFrame | None:
    """
    Fallback: Google Sheets API v4 via gspread service account.
    Credentials are read from the GOOGLE_SHEETS_CREDENTIALS env var
    (set as GitHub Secret — contains the full service account JSON).
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
        if not creds_json:
            log.error("GOOGLE_SHEETS_CREDENTIALS env var not set.")
            return None

        creds_info = json.loads(creds_json)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        gc = gspread.authorize(creds)

        sh = gc.open_by_key(SHEET_ID)
        ws = sh.worksheet(worksheet_name)
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        log.info(f"  → {len(df)} rows fetched via service account ({worksheet_name}).")
        return df
    except Exception as e:
        log.error(f"Service account fetch failed for '{worksheet_name}': {e}")
        return None


def fetch_stock_universe() -> pd.DataFrame | None:
    df = _fetch_csv_public(PUBLIC_CSV_URL_STOCKS)
    if df is None:
        df = _fetch_csv_service_account("Stock Fundamentals")
    return df


def fetch_etf_universe() -> pd.DataFrame | None:
    df = _fetch_csv_public(PUBLIC_CSV_URL_ETFS)
    if df is None:
        df = _fetch_csv_service_account("Stock Summary")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Processing
# ─────────────────────────────────────────────────────────────────────────────

def process_stock_universe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean the raw stock DataFrame:
    - Keep only known columns (add missing ones as NaN)
    - Normalise tickers
    - Drop rows with invalid tickers
    - Add fetch timestamp
    """
    # Align to expected columns (adds missing as NaN, drops extras)
    for col in STOCK_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[STOCK_COLUMNS].copy()

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
    """
    Merge the Google Sheet ETF tab with the hard-coded Strategy 5 ETF master list.
    Always ensure the 13 Strategy 5 ETFs are present.
    """
    s5_df = pd.DataFrame(STRATEGY5_ETF_MASTER)
    s5_df["Ticker (NSE)"] = s5_df["Ticker (NSE)"].apply(
        lambda x: normalise_ticker(x) or x + ".NS"
    )
    s5_df["_source"] = "strategy5_master"

    if df is not None and len(df) > 0:
        # Normalise sheet tickers
        if "Ticker (NSE)" in df.columns:
            df["Ticker (NSE)"] = df["Ticker (NSE)"].apply(normalise_ticker)
            df = df[df["Ticker (NSE)"].notna()].copy()
        df["_source"] = "google_sheet"

        # Merge: sheet rows + any S5 ETFs not already in sheet
        sheet_tickers = set(df["Ticker (NSE)"].tolist())
        extra_s5 = s5_df[~s5_df["Ticker (NSE)"].isin(sheet_tickers)]
        combined = pd.concat([df, extra_s5], ignore_index=True)
    else:
        log.warning("No ETF data from Google Sheet — using Strategy 5 master list only.")
        combined = s5_df.copy()

    combined["_fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log.info(f"ETF universe ready: {len(combined)} ETFs.")
    return combined


# ─────────────────────────────────────────────────────────────────────────────
# Change detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_changes(
    current: pd.DataFrame,
    prev_path: Path,
) -> pd.DataFrame:
    """
    Compare current stock universe with the previous run's copy.
    Detects:
      - Added tickers
      - Removed tickers
      - TA Status changes
    Returns a DataFrame logged to universe_changes.csv.
    """
    changes = []
    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not prev_path.exists():
        log.info("No previous universe file — skipping change detection.")
        return pd.DataFrame()

    try:
        prev = pd.read_csv(prev_path)
    except Exception as e:
        log.warning(f"Could not read previous universe: {e}")
        return pd.DataFrame()

    curr_tickers = set(current["Ticker (NSE)"].tolist())
    prev_tickers = set(prev["Ticker (NSE)"].tolist())

    # Added
    for t in sorted(curr_tickers - prev_tickers):
        row = current[current["Ticker (NSE)"] == t].iloc[0]
        changes.append({
            "run_at": run_ts,
            "change_type": "ADDED",
            "ticker": t,
            "company": row.get("Company Name", ""),
            "detail": f"Added to master list | TA Status: {row.get('TA Status', '')}",
        })

    # Removed
    for t in sorted(prev_tickers - curr_tickers):
        row = prev[prev["Ticker (NSE)"] == t].iloc[0]
        changes.append({
            "run_at": run_ts,
            "change_type": "REMOVED",
            "ticker": t,
            "company": row.get("Company Name", ""),
            "detail": f"Removed from master list | Was TA Status: {row.get('TA Status', '')}",
        })

    # TA Status changes (for stocks in both)
    common = curr_tickers & prev_tickers
    curr_idx = current.set_index("Ticker (NSE)")
    prev_idx = prev.set_index("Ticker (NSE)")

    for t in sorted(common):
        try:
            curr_status = str(curr_idx.loc[t, "TA Status"]).strip()
            prev_status = str(prev_idx.loc[t, "TA Status"]).strip()
            if curr_status != prev_status:
                changes.append({
                    "run_at": run_ts,
                    "change_type": "TA_STATUS_CHANGED",
                    "ticker": t,
                    "company": curr_idx.loc[t, "Company Name"],
                    "detail": f"TA Status: '{prev_status}' → '{curr_status}'",
                })
        except Exception:
            pass

    if changes:
        log.info(f"Universe changes detected: {len(changes)} changes.")
        for c in changes:
            log.info(f"  [{c['change_type']}] {c['ticker']} — {c['detail']}")
    else:
        log.info("No changes detected in universe since last run.")

    return pd.DataFrame(changes)


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def run() -> dict:
    """
    Full universe refresh cycle:
      1. Fetch Google Sheet (stocks + ETFs)
      2. Process & normalise
      3. Detect changes vs previous run
      4. Save CSVs
      5. Return summary dict for use by orchestrator scripts
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    stock_path      = DATA_DIR / "stock_universe.csv"
    etf_path        = DATA_DIR / "etf_universe.csv"
    prev_stock_path = DATA_DIR / "stock_universe_prev.csv"
    changes_path    = DATA_DIR / "universe_changes.csv"

    # ── 1. Backup previous run ───────────────────────────────────────────────
    if stock_path.exists():
        import shutil
        shutil.copy(stock_path, prev_stock_path)
        log.info("Previous stock universe backed up.")

    # ── 2. Fetch ─────────────────────────────────────────────────────────────
    raw_stocks = fetch_stock_universe()
    raw_etfs   = fetch_etf_universe()

    if raw_stocks is None:
        log.error("CRITICAL: Could not fetch stock universe from any source.")
        raise RuntimeError("Stock universe fetch failed.")

    # ── 3. Process ───────────────────────────────────────────────────────────
    stocks = process_stock_universe(raw_stocks)
    etfs   = process_etf_universe(raw_etfs)

    # ── 4. Detect changes ────────────────────────────────────────────────────
    changes = detect_changes(stocks, prev_stock_path)

    # Append to cumulative changes log
    if not changes.empty:
        if changes_path.exists():
            existing = pd.read_csv(changes_path)
            changes = pd.concat([existing, changes], ignore_index=True)
        changes.to_csv(changes_path, index=False)
        log.info(f"Changes log saved → {changes_path}")

    # ── 5. Save ──────────────────────────────────────────────────────────────
    stocks.to_csv(stock_path, index=False)
    etfs.to_csv(etf_path, index=False)
    log.info(f"Saved: {stock_path} ({len(stocks)} stocks)")
    log.info(f"Saved: {etf_path} ({len(etfs)} ETFs)")

    summary = {
        "stock_count":    len(stocks),
        "etf_count":      len(etfs),
        "stock_tickers":  stocks["Ticker (NSE)"].tolist(),
        "etf_tickers":    etfs["Ticker (NSE)"].tolist(),
        "changes_count":  len(changes) if not changes.empty else 0,
        "fetched_at":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return summary


if __name__ == "__main__":
    result = run()
    print("\n── Universe Loader Summary ──────────────────────")
    print(f"  Stocks : {result['stock_count']}")
    print(f"  ETFs   : {result['etf_count']}")
    print(f"  Changes: {result['changes_count']}")
    print(f"  Time   : {result['fetched_at']}")
