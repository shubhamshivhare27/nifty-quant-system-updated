"""
universe_loader.py
------------------
Fetches the user-maintained Google Sheet master list.
Updated to match actual Google Sheet column names.
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
GID_STOCKS = "1666453875"
GID_ETFS   = "0"

PUBLIC_CSV_URL_STOCKS = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
    f"/export?format=csv&gid={GID_STOCKS}"
)
PUBLIC_CSV_URL_ETFS = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
    f"/export?format=csv&gid={GID_ETFS}"
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ── Actual column name in your Google Sheet for ticker symbols ────────────────
TICKER_COL = "Ticker symbols"   # ← matches your sheet's column R header

# Strategy 5 — fixed ETF master list
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
# Sheet fetching
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_csv_public(url: str) -> pd.DataFrame | None:
    try:
        log.info(f"Trying public CSV export: {url}")
        resp = requests.get(url, timeout=30)
        if "<html" in resp.text[:200].lower():
            log.warning("Sheet is private — public CSV export rejected.")
            return None
        df = pd.read_csv(io.StringIO(resp.text))
        log.info(f"  → {len(df)} rows fetched via public CSV.")
        log.info(f"  Columns found: {list(df.columns)}")
        return df
    except Exception as e:
        log.warning(f"Public CSV fetch failed: {e}")
        return None


def _fetch_csv_service_account(worksheet_name: str) -> pd.DataFrame | None:
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
    Clean raw stock DataFrame.
    Automatically finds the ticker column regardless of exact name.
    """
    df = df.copy()

    # ── Find ticker column flexibly ───────────────────────────────────────────
    ticker_col_found = None
    candidates = [
        "Ticker symbols", "Ticker (NSE)", "Ticker Symbol", "Ticker",
        "NSE Ticker", "Symbol", "NSE Symbol", "ticker", "TICKER"
    ]
    for c in candidates:
        if c in df.columns:
            ticker_col_found = c
            break

    # Also try partial match as last resort
    if ticker_col_found is None:
        for col in df.columns:
            if "ticker" in col.lower() or "symbol" in col.lower():
                ticker_col_found = col
                break

    if ticker_col_found is None:
        log.error(f"Could not find ticker column. Available columns: {list(df.columns)}")
        raise KeyError(f"No ticker column found in sheet. Columns: {list(df.columns)}")

    log.info(f"Using ticker column: '{ticker_col_found}'")

    # Rename to standard internal name
    df = df.rename(columns={ticker_col_found: "Ticker (NSE)"})

    # Find TA Status column flexibly
    ta_col = None
    for c in df.columns:
        if "ta status" in c.lower() or (c.strip().lower() in ["ta status", "status"]):
            ta_col = c
            break
    if ta_col and ta_col != "TA Status":
        df = df.rename(columns={ta_col: "TA Status"})

    # Find company name column
    name_col = None
    for c in df.columns:
        if c.lower() in ["name", "company name", "company"]:
            name_col = c
            break
    if name_col and name_col != "Company Name":
        df = df.rename(columns={name_col: "Company Name"})

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
        # Find ticker column in ETF sheet
        ticker_col_found = None
        for c in df.columns:
            if "ticker" in c.lower() or "symbol" in c.lower():
                ticker_col_found = c
                break
        if ticker_col_found:
            df = df.rename(columns={ticker_col_found: "Ticker (NSE)"})
            df["Ticker (NSE)"] = df["Ticker (NSE)"].apply(normalise_ticker)
            df = df[df["Ticker (NSE)"].notna()].copy()
        df["_source"] = "google_sheet"

        sheet_tickers = set(df["Ticker (NSE)"].tolist()) if "Ticker (NSE)" in df.columns else set()
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

def detect_changes(current: pd.DataFrame, prev_path: Path) -> pd.DataFrame:
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

    for t in sorted(curr_tickers - prev_tickers):
        row = current[current["Ticker (NSE)"] == t].iloc[0]
        changes.append({
            "run_at": run_ts, "change_type": "ADDED", "ticker": t,
            "company": row.get("Company Name", ""),
            "detail": f"Added to master list | TA Status: {row.get('TA Status', '')}",
        })

    for t in sorted(prev_tickers - curr_tickers):
        row = prev[prev["Ticker (NSE)"] == t].iloc[0]
        changes.append({
            "run_at": run_ts, "change_type": "REMOVED", "ticker": t,
            "company": row.get("Company Name", ""),
            "detail": f"Removed from master list | Was TA Status: {row.get('TA Status', '')}",
        })

    common = curr_tickers & prev_tickers
    curr_idx = current.set_index("Ticker (NSE)")
    prev_idx = prev.set_index("Ticker (NSE)")

    for t in sorted(common):
        try:
            curr_status = str(curr_idx.loc[t, "TA Status"]).strip() if "TA Status" in curr_idx.columns else ""
            prev_status = str(prev_idx.loc[t, "TA Status"]).strip() if "TA Status" in prev_idx.columns else ""
            if curr_status != prev_status:
                changes.append({
                    "run_at": run_ts, "change_type": "TA_STATUS_CHANGED", "ticker": t,
                    "company": curr_idx.loc[t, "Company Name"] if "Company Name" in curr_idx.columns else "",
                    "detail": f"TA Status: '{prev_status}' → '{curr_status}'",
                })
        except Exception:
            pass

    if changes:
        log.info(f"Universe changes detected: {len(changes)} changes.")
    else:
        log.info("No changes detected in universe since last run.")

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
        log.info("Previous stock universe backed up.")

    raw_stocks = fetch_stock_universe()
    raw_etfs   = fetch_etf_universe()

    if raw_stocks is None:
        log.error("CRITICAL: Could not fetch stock universe from any source.")
        raise RuntimeError("Stock universe fetch failed.")

    stocks = process_stock_universe(raw_stocks)
    etfs   = process_etf_universe(raw_etfs)

    changes = detect_changes(stocks, prev_stock_path)

    if not changes.empty:
        if changes_path.exists():
            existing = pd.read_csv(changes_path)
            changes = pd.concat([existing, changes], ignore_index=True)
        changes.to_csv(changes_path, index=False)
        log.info(f"Changes log saved → {changes_path}")

    stocks.to_csv(stock_path, index=False)
    etfs.to_csv(etf_path, index=False)
    log.info(f"Saved: {stock_path} ({len(stocks)} stocks)")
    log.info(f"Saved: {etf_path} ({len(etfs)} ETFs)")

    summary = {
        "stock_count":   len(stocks),
        "etf_count":     len(etfs),
        "stock_tickers": stocks["Ticker (NSE)"].tolist(),
        "etf_tickers":   etfs["Ticker (NSE)"].tolist(),
        "changes_count": len(changes) if not changes.empty else 0,
        "fetched_at":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return summary


if __name__ == "__main__":
    result = run()
    print("\n── Universe Loader Summary ──────────────────────")
    print(f"  Stocks : {result['stock_count']}")
    print(f"  ETFs   : {result['etf_count']}")
    print(f"  Changes: {result['changes_count']}")
    print(f"  Time   : {result['fetched_at']}")
