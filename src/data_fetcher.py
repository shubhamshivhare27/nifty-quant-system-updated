"""
data_fetcher.py
---------------
Fetches OHLCV price data for NSE stocks and ETFs.

Primary  : Upstox Historical Candle API v2 (dividend-adjusted, matches TradingView ADJ)
Fallback : yfinance with auto_adjust=True  (NEVER auto_adjust=False)

Supported intervals: daily, weekly, monthly
Graceful degradation: Upstox fails → yfinance → skip + log. Never crash.
"""

import os
import time
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

log = logging.getLogger("data_fetcher")

# ── Upstox instrument key lookup ──────────────────────────────────────────────
# Maps SYMBOL.NS → Upstox instrument_key (e.g. NSE_EQ|INE002A01018)
# Loaded once from data/upstox_symbols.csv
_UPSTOX_KEY_CACHE: dict[str, str] = {}

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

UPSTOX_INTERVAL_MAP = {
    "daily":   "day",
    "weekly":  "week",
    "monthly": "month",
}

YFINANCE_INTERVAL_MAP = {
    "daily":   "1d",
    "weekly":  "1wk",
    "monthly": "1mo",
}


# ─────────────────────────────────────────────────────────────────────────────
# Upstox instrument key helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_upstox_symbols():
    """Load the Upstox symbol → instrument_key mapping once."""
    global _UPSTOX_KEY_CACHE
    if _UPSTOX_KEY_CACHE:
        return

    sym_path = DATA_DIR / "upstox_symbols.csv"
    if not sym_path.exists():
        log.warning("upstox_symbols.csv not found — will attempt ticker-based key construction.")
        return

    try:
        df = pd.read_csv(sym_path)
        # Expected columns: ticker (SYMBOL.NS), instrument_key
        for _, row in df.iterrows():
            _UPSTOX_KEY_CACHE[str(row["ticker"]).strip()] = str(row["instrument_key"]).strip()
        log.info(f"Loaded {len(_UPSTOX_KEY_CACHE)} Upstox instrument keys.")
    except Exception as e:
        log.warning(f"Could not load upstox_symbols.csv: {e}")


def _get_upstox_instrument_key(ticker: str) -> str:
    """
    Return the Upstox instrument_key for a given SYMBOL.NS ticker.
    Falls back to constructed key: NSE_EQ|{SYMBOL} if not found in lookup.
    """
    _load_upstox_symbols()
    if ticker in _UPSTOX_KEY_CACHE:
        return _UPSTOX_KEY_CACHE[ticker]

    # Construct a best-guess key (works for most NSE equities)
    symbol = ticker.replace(".NS", "")
    key = f"NSE_EQ|{symbol}"
    log.debug(f"No Upstox key for {ticker} — using constructed key: {key}")
    return key


# ─────────────────────────────────────────────────────────────────────────────
# Upstox token management
# ─────────────────────────────────────────────────────────────────────────────

def _get_upstox_token() -> str | None:
    """
    Returns the current Upstox access token.
    Token is stored in UPSTOX_TOKEN env var (refreshed daily by GitHub Actions).
    """
    token = os.environ.get("UPSTOX_TOKEN", "").strip()
    if not token:
        log.warning("UPSTOX_TOKEN env var not set — will fall back to yfinance.")
        return None
    return token


# ─────────────────────────────────────────────────────────────────────────────
# Upstox fetch
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_upstox(
    ticker: str,
    interval: str,
    from_date: str,
    to_date: str,
    token: str,
) -> pd.DataFrame | None:
    """
    Fetch OHLCV from Upstox Historical Candle API v2.

    URL pattern:
    https://api.upstox.com/v2/historical-candle/{instrument_key}/{interval}/{to}/{from}

    Returns DataFrame with columns: date, open, high, low, close, volume
    """
    instrument_key = _get_upstox_instrument_key(ticker)
    # URL-encode the pipe character in instrument_key
    encoded_key = instrument_key.replace("|", "%7C")
    upstox_interval = UPSTOX_INTERVAL_MAP.get(interval, "day")

    url = (
        f"https://api.upstox.com/v2/historical-candle"
        f"/{encoded_key}/{upstox_interval}/{to_date}/{from_date}"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 401:
            log.warning(f"Upstox 401 for {ticker} — token expired.")
            return None
        if resp.status_code == 429:
            log.warning(f"Upstox rate limit hit for {ticker} — sleeping 5s.")
            time.sleep(5)
            resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            log.warning(f"Upstox {resp.status_code} for {ticker}: {resp.text[:200]}")
            return None

        data = resp.json()
        candles = data.get("data", {}).get("candles", [])
        if not candles:
            log.warning(f"Upstox returned 0 candles for {ticker} ({interval}).")
            return None

        # Upstox candle format: [timestamp, open, high, low, close, volume, oi]
        df = pd.DataFrame(candles, columns=["date", "open", "high", "low", "close", "volume", "oi"])
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        df = df[["date", "open", "high", "low", "close", "volume"]].copy()
        df = df.sort_values("date").reset_index(drop=True)

        # Cast to float
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["close"])
        log.debug(f"Upstox: {ticker} ({interval}) → {len(df)} candles")
        return df

    except Exception as e:
        log.warning(f"Upstox fetch exception for {ticker}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# yfinance fallback
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_yfinance(
    ticker: str,
    interval: str,
    from_date: str,
    to_date: str,
) -> pd.DataFrame | None:
    """
    Fallback price fetch using yfinance with auto_adjust=True.
    NEVER uses auto_adjust=False (unadjusted prices break indicator levels).
    """
    try:
        import yfinance as yf

        yf_interval = YFINANCE_INTERVAL_MAP.get(interval, "1d")

        # yfinance period calculation
        from_dt = datetime.strptime(from_date, "%Y-%m-%d")
        to_dt   = datetime.strptime(to_date,   "%Y-%m-%d") + timedelta(days=1)

        tk = yf.Ticker(ticker)
        df = tk.history(
            start=from_dt.strftime("%Y-%m-%d"),
            end=to_dt.strftime("%Y-%m-%d"),
            interval=yf_interval,
            auto_adjust=True,   # CRITICAL — always adjusted
            actions=False,
        )

        if df is None or df.empty:
            log.warning(f"yfinance returned empty for {ticker} ({interval}).")
            return None

        df = df.reset_index()
        date_col = "Date" if "Date" in df.columns else "Datetime"
        df = df.rename(columns={
            date_col: "date",
            "Open":   "open",
            "High":   "high",
            "Low":    "low",
            "Close":  "close",
            "Volume": "volume",
        })
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        df = df[["date", "open", "high", "low", "close", "volume"]].copy()
        df = df.sort_values("date").reset_index(drop=True)

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["close"])
        log.debug(f"yfinance: {ticker} ({interval}) → {len(df)} candles")
        return df

    except Exception as e:
        log.warning(f"yfinance fetch exception for {ticker}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_ohlcv(
    ticker: str,
    interval: Literal["daily", "weekly", "monthly"],
    lookback_years: int = 5,
    to_date: str | None = None,
) -> pd.DataFrame | None:
    """
    Fetch OHLCV for a single ticker and interval.

    Returns a DataFrame with columns: date, open, high, low, close, volume
    Returns None if both Upstox and yfinance fail (caller should skip + log).

    Args:
        ticker        : NSE ticker in SYMBOL.NS format
        interval      : 'daily', 'weekly', or 'monthly'
        lookback_years: how many years of history to fetch (default 5)
        to_date       : end date as 'YYYY-MM-DD' (default: today)
    """
    if to_date is None:
        to_date = datetime.today().strftime("%Y-%m-%d")

    from_dt = datetime.today() - timedelta(days=lookback_years * 365 + 30)
    from_date = from_dt.strftime("%Y-%m-%d")

    token = _get_upstox_token()

    # ── Primary: Upstox ──────────────────────────────────────────────────────
    if token:
        df = _fetch_upstox(ticker, interval, from_date, to_date, token)
        if df is not None and len(df) >= 20:
            df["_source"] = "upstox"
            return df
        log.info(f"{ticker} ({interval}): Upstox failed — falling back to yfinance.")

    # ── Fallback: yfinance ───────────────────────────────────────────────────
    df = _fetch_yfinance(ticker, interval, from_date, to_date)
    if df is not None and len(df) >= 20:
        df["_source"] = "yfinance"
        return df

    log.error(f"{ticker} ({interval}): Both Upstox and yfinance failed — skipping.")
    return None


def fetch_multi_timeframe(
    ticker: str,
    intervals: list[str],
    lookback_years: int = 5,
    to_date: str | None = None,
) -> dict[str, pd.DataFrame | None]:
    """
    Fetch multiple timeframes for a single ticker in one call.

    Returns:
        {
            "daily":   DataFrame or None,
            "weekly":  DataFrame or None,
            "monthly": DataFrame or None,
        }
    """
    result = {}
    for interval in intervals:
        result[interval] = fetch_ohlcv(ticker, interval, lookback_years, to_date)
        time.sleep(0.1)  # polite rate limiting
    return result


def fetch_batch(
    tickers: list[str],
    interval: Literal["daily", "weekly", "monthly"],
    lookback_years: int = 5,
    to_date: str | None = None,
    delay_seconds: float = 0.15,
) -> dict[str, pd.DataFrame | None]:
    """
    Fetch OHLCV for a list of tickers (same interval).
    Returns dict: {ticker: DataFrame or None}

    Includes a small delay between requests to avoid rate limiting.
    """
    results = {}
    total = len(tickers)
    for i, ticker in enumerate(tickers, 1):
        log.info(f"Fetching [{i}/{total}] {ticker} ({interval})")
        results[ticker] = fetch_ohlcv(ticker, interval, lookback_years, to_date)
        if i < total:
            time.sleep(delay_seconds)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Weekly candle alignment helper
# ─────────────────────────────────────────────────────────────────────────────

def get_last_trading_day_of_week(df_daily: pd.DataFrame) -> pd.DataFrame:
    """
    Build weekly candles from daily data using the LAST available trading day
    of each ISO week. This correctly handles NSE holidays (~25/year) where
    Friday may not be a trading day.

    This is more accurate than yfinance's fixed-Friday weekly bars.
    """
    df = df_daily.copy()
    df["week"] = df["date"].dt.isocalendar().week.astype(int)
    df["year"] = df["date"].dt.isocalendar().year.astype(int)

    weekly = df.groupby(["year", "week"]).agg(
        date   = ("date",   "last"),
        open   = ("open",   "first"),
        high   = ("high",   "max"),
        low    = ("low",    "min"),
        close  = ("close",  "last"),
        volume = ("volume", "sum"),
    ).reset_index(drop=True)

    weekly = weekly.sort_values("date").reset_index(drop=True)
    return weekly


def get_last_trading_day_of_month(df_daily: pd.DataFrame) -> pd.DataFrame:
    """
    Build monthly candles from daily data using the LAST available trading day
    of each calendar month.
    """
    df = df_daily.copy()
    df["month"] = df["date"].dt.to_period("M")

    monthly = df.groupby("month").agg(
        date   = ("date",   "last"),
        open   = ("open",   "first"),
        high   = ("high",   "max"),
        low    = ("low",    "min"),
        close  = ("close",  "last"),
        volume = ("volume", "sum"),
    ).reset_index(drop=True)

    monthly = monthly.sort_values("date").reset_index(drop=True)
    return monthly


if __name__ == "__main__":
    # Quick smoke test
    logging.basicConfig(level=logging.INFO)
    log.info("Testing data_fetcher with ITC.NS ...")
    df = fetch_ohlcv("ITC.NS", "weekly", lookback_years=2)
    if df is not None:
        print(f"\nITC.NS weekly: {len(df)} rows")
        print(df.tail(3).to_string(index=False))
    else:
        print("Fetch failed for ITC.NS")
