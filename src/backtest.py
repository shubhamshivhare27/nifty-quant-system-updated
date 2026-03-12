"""
backtest_all_strategies_final.py
=================================
FINAL confirmed backtest — all 5 strategies, 2020-2026 and 2023-2026.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
UNIVERSE — where each strategy gets its stocks
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  S1  NIFTY100_STOCKS  (all 100 Nifty 100 stocks)
      Universe pre-filter: RSI>60 on Daily AND Weekly AND Monthly at bar time.

  S2  NIFTY100_STOCKS  (all 100 Nifty 100 stocks)
      Universe filter: RSI14 > 60 on Daily AND Weekly AND Monthly.

  S3  DEFAULT_STOCKS  (same as S1 — no MCap filter, universe filter=NONE)

  S4  DEFAULT_STOCKS  (same as S1 — no MCap filter, universe filter=NONE)

  S5  ETF_TICKERS     (13 ETFs — hardcoded master ETF list, no filter)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SETUP / ENTRY / EXIT — confirmed logic for each strategy
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  S1  Monthly EMA20 Breakout  [UNCHANGED — logic frozen]
    Timeframe : Monthly candles
    Universe  : RSI14 > 60 on Daily AND Weekly AND Monthly (AND-gate,
                checked at time of monthly bar close)
    Setup     : EMA10 > EMA20 > EMA50 on monthly  AND  close > EMA50
    Entry     : previous month close < EMA20  AND  current close > EMA20
                (price crosses above monthly EMA20 from below)
    Exit      : EMA10 crosses below EMA20 (monthly)
                AND  EMA10 slope < 0  AND  EMA20 slope < 0

  S2  Weekly EMA Pullback Cross  [CONFIRMED]
    Timeframe : Weekly candles; monthly used for pre-condition check
    Universe  : All Nifty 100 stocks
    Filter    : RSI14 > 60 on Daily AND Weekly AND Monthly (AND-gate)
    Pre-cond  : On monthly chart: EMA10 > EMA20 > EMA50
                (ensures stock is in a long-term uptrend at entry week)
    Setup     : Last week: EMA10 < EMA20  (stock pulled back on weekly)
    Entry     : This week: EMA10 crosses above EMA20
                (pullback ended, weekly trend resumed)
    Exit      : Weekly EMA10 crosses below EMA20

  S3  Monthly SSF50 Breakout  [Option C — CONFIRMED]
    Timeframe : Monthly candles
    Universe  : No filter — all stocks from master list are eligible
    Setup     : Previous month close was below SSF50
                AND  below SSF200  AND  below SSF250
                (stock was in deep downtrend on all three SSF levels)
    Entry     : previous close < SSF50  AND  current close > SSF50
                (price breaks above SSF50 this month)
                AND  RSI14 > RSI14_MA(14)   (RSI14 above its 14-bar SMA)
                AND  MACD line > MACD signal line
                AND  MACD line > 0           [Option C gate]
    Exit      : MACD line crosses below MACD signal line (monthly)
                (was above signal last month, now below — bearish cross)

  S4  Weekly SSF50 Breakout  [Option D — CONFIRMED]
    Timeframe : Weekly candles
    Universe  : No filter — all stocks from master list are eligible
    Setup     : Previous week close < SSF50 ONLY
                (SSF200 and SSF250 no longer required — Option D change)
    Entry     : previous close < SSF50  AND  current close > SSF50
                (price breaks above SSF50 this week)
                AND  RSI14 > RSI14_MA(14)
                AND  MACD line > MACD signal line
                AND  MACD line > 0   AND  MACD signal > 0
                (both MACD components must be in positive territory)
    Exit      : MACD line crosses below MACD signal line (weekly)

  S5  Weekly ETF SSF50 Breakout  [Modified-1 — CONFIRMED]
    Timeframe : Weekly candles
    Universe  : All 13 ETFs from master list — no pre-filter applied
    Setup     : Previous week close < SSF50
    Entry     : previous close < SSF50  AND  current close > SSF50
                (ETF breaks above SSF50)
                AND  RSI14 > RSI14_MA(14)   [Modified-1 gate]
    Exit      : NO EXIT CONDITION — all trades held open to today's date/price
                 (exit date = date backtest is run, exit price = latest weekly close)
                     (cp > SSF50_prev  AND  cn < SSF50_current)
                     This is a conservative proxy for the manual exit.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SETUP
  pip install yfinance pandas numpy

USAGE
  # Default: runs both 2020-2026 and 2023-2026 windows
  python backtest_all_strategies_final.py

  # Only specific strategies
  python backtest_all_strategies_final.py --strategies S3 S4 S5

  # Full Nifty 500 universe
  python backtest_all_strategies_final.py --universe nifty500.csv

OUTPUT  (saved to backtest_results/)
  summary_2020-2026.csv / summary_2023-2026.csv  — per-strategy metrics
  all_trades_2020-2026.csv / all_trades_2023-2026.csv
  s1_trades_*.csv ... s5_trades_*.csv
  backtest_report_final.html  — visual report with both windows side-by-side

NOTES
  • No lookahead bias — signals use only data up to and including bar i
  • RSI on Daily/Monthly aligned by date-matching to the weekly bar date
    (not by taking the last available value — that was a bug in v1)
  • EMA warmup uses TradingView convention: seed EMA with SMA of first N bars
  • S5 has NO exit condition. Every entry is held to today. Exit price = latest weekly close.
  • MACD(12,26,9) — EMA(12) - EMA(26), signal = EMA(9) of MACD line
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import argparse
import logging
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backtest")

try:
    import yfinance as yf
except ImportError:
    log.error("yfinance not installed.  Run:  pip install yfinance pandas numpy")
    sys.exit(1)

OUT   = Path("backtest_results")
OUT.mkdir(exist_ok=True)
TODAY = datetime.today().strftime("%Y-%m-%d")

# ─────────────────────────────────────────────────────────────────────────────
# UNIVERSE DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

# S1, S3, S4 — representative 50-stock Nifty500 sample.
# Pass --universe nifty500.csv for a full 500-stock run.
# ── Nifty 100 — used as universe for S1 and S2 ───────────────────────────────
# S1: RSI>60 D+W+M filter applied at bar time (further narrows the set)
# S2: RSI>60 D+W+M filter applied at bar time (no MCap gate)
# S3 / S4: use DEFAULT_STOCKS below (no universe pre-filter)
NIFTY100_STOCKS = [
    # Nifty 50
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS",
    "HINDUNILVR.NS","BHARTIARTL.NS","ITC.NS","KOTAKBANK.NS","LT.NS",
    "AXISBANK.NS","BAJFINANCE.NS","ASIANPAINT.NS","MARUTI.NS","HCLTECH.NS",
    "TITAN.NS","SUNPHARMA.NS","WIPRO.NS","ULTRACEMCO.NS","NESTLEIND.NS",
    "POWERGRID.NS","NTPC.NS","TECHM.NS","BAJAJFINSV.NS","ONGC.NS",
    "SBILIFE.NS","ADANIENT.NS","GRASIM.NS","DIVISLAB.NS","TATAMOTORS.NS",
    "INDUSINDBK.NS","CIPLA.NS","JSWSTEEL.NS","TATACONSUM.NS","DRREDDY.NS",
    "EICHERMOT.NS","BPCL.NS","SBIN.NS","COALINDIA.NS","HEROMOTOCO.NS",
    "BRITANNIA.NS","APOLLOHOSP.NS","HINDALCO.NS","DABUR.NS","PIDILITIND.NS",
    "MARICO.NS","SHRIRAMFIN.NS","BAJAJ-AUTO.NS","TATAPOWER.NS","VEDL.NS",
    # Nifty Next 50 (completing Nifty 100)
    "ADANIPORTS.NS","ADANIGREEN.NS","ADANITRANS.NS","AMBUJACEM.NS",
    "AUROPHARMA.NS","BAJAJHLDNG.NS","BANKBARODA.NS","BEL.NS","BERGEPAINT.NS",
    "BIOCON.NS","BOSCHLTD.NS","CANBK.NS","CHOLAFIN.NS","COLPAL.NS",
    "CONCOR.NS","DLF.NS","DMART.NS","GAIL.NS","GODREJCP.NS",
    "GODREJPROP.NS","HAL.NS","HAVELLS.NS","HDFCLIFE.NS","ICICIlombard.NS",
    "ICICIPRUDENTIAL.NS","INDUSTOWER.NS","IOC.NS","IRCTC.NS","JIOFIN.NS",
    "LICI.NS","LODHA.NS","LTF.NS","LTIM.NS","MOTHERSON.NS",
    "MPHASIS.NS","MRF.NS","NAUKRI.NS","NHPC.NS","NMDC.NS",
    "OFSS.NS","PAGEIND.NS","PETRONET.NS","PFC.NS","PIDILITIND.NS",
    "PNB.NS","RECLTD.NS","SAIL.NS","SIEMENS.NS","SRF.NS",
    "TORNTPHARM.NS","TRENT.NS","UBL.NS","UNIONBANK.NS","VBL.NS",
    "ZOMATO.NS","ZYDUSLIFE.NS",
]

# S3 / S4 — representative Nifty 500 sample (no universe pre-filter)
# Pass --universe nifty500.csv to override for a full 500-stock run
DEFAULT_STOCKS = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS",
    "HINDUNILVR.NS","BHARTIARTL.NS","ITC.NS","KOTAKBANK.NS","LT.NS",
    "AXISBANK.NS","BAJFINANCE.NS","ASIANPAINT.NS","MARUTI.NS","HCLTECH.NS",
    "TITAN.NS","SUNPHARMA.NS","WIPRO.NS","ULTRACEMCO.NS","NESTLEIND.NS",
    "POWERGRID.NS","NTPC.NS","TECHM.NS","BAJAJFINSV.NS","ONGC.NS",
    "SBILIFE.NS","ADANIENT.NS","GRASIM.NS","DIVISLAB.NS","TATAMOTORS.NS",
    "INDUSINDBK.NS","CIPLA.NS","JSWSTEEL.NS","TATACONSUM.NS","DRREDDY.NS",
    "EICHERMOT.NS","BPCL.NS","SBIN.NS","COALINDIA.NS","HEROMOTOCO.NS",
    "BRITANNIA.NS","APOLLOHOSP.NS","HINDALCO.NS","DABUR.NS","PIDILITIND.NS",
    "MARICO.NS","MUTHOOTFIN.NS","BERGEPAINT.NS","TORNTPHARM.NS","LUPIN.NS",
]

# S5 — master ETF list (13 ETFs, no filter applied)
ETF_TICKERS = [
    "NIFTYBEES.NS","JUNIORBEES.NS","SETFNIF50.NS",
    "BANKBEES.NS","AUTOBEES.NS","INFRABEES.NS","NIFTYREALTY.NS",
    "MON100.NS","MASP500.NS",
    "AIQ","ROBT","DTCR",
]

# ─────────────────────────────────────────────────────────────────────────────
# DATA FETCHER + DATE-ALIGNED RSI HELPER
# ─────────────────────────────────────────────────────────────────────────────

_cache: dict = {}

def _fetch_raw(ticker: str, interval: str, years: int = 9) -> pd.DataFrame | None:
    key = (ticker, interval)
    if key in _cache:
        return _cache[key]
    try:
        end   = datetime.today()
        start = end - timedelta(days=365 * (years + 1))
        raw = yf.download(
            ticker, start=start, end=end,
            interval=interval, auto_adjust=True, progress=False,
        )
        if raw is None or len(raw) < 20:
            _cache[key] = None; return None
        raw = raw.reset_index()
        raw.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                       for c in raw.columns]
        date_col = "datetime" if "datetime" in raw.columns else "date"
        raw = raw.rename(columns={date_col: "date"})
        raw = raw[["date", "close"]].dropna().reset_index(drop=True)
        raw["date"] = pd.to_datetime(raw["date"]).dt.tz_localize(None)
        _cache[key] = raw
    except Exception as e:
        log.debug(f"Fetch {ticker} {interval}: {e}")
        _cache[key] = None
    return _cache[key]

def fetch_multi(ticker, intervals=("1d","1wk","1mo"), years=9):
    return {iv: _fetch_raw(ticker, iv, years) for iv in intervals}

def fetch(ticker, interval, years=9):
    return _fetch_raw(ticker, interval, years)

def align_series_to_dates(
    target_dates: pd.Series,
    source_df: pd.DataFrame,
    source_series: pd.Series,
) -> pd.Series:
    """
    For each date in target_dates, return the most recent value from
    source_series whose corresponding source_df['date'] is <= target date.
    This correctly aligns e.g. daily RSI values to weekly bar dates,
    avoiding the lookahead bug of always taking the last available value.
    """
    src_dates = source_df["date"].values
    src_vals  = source_series.values
    result = np.full(len(target_dates), np.nan)
    for i, td in enumerate(target_dates):
        mask = src_dates <= td
        if mask.any():
            result[i] = src_vals[mask][-1]
    return pd.Series(result, dtype=float)

# ─────────────────────────────────────────────────────────────────────────────
# INDICATORS  (self-contained — no dependency on src/)
# ─────────────────────────────────────────────────────────────────────────────

def ema_ind(series: pd.Series, period: int) -> pd.Series:
    """TradingView-style EMA — seeded with SMA of first `period` bars."""
    s   = series.reset_index(drop=True).astype(float)
    out = pd.Series(np.nan, index=s.index)
    fv  = s.first_valid_index()
    if fv is None or fv + period > len(s):
        return out
    out.iloc[fv + period - 1] = s.iloc[fv : fv + period].mean()
    k = 2.0 / (period + 1)
    for i in range(fv + period, len(s)):
        v = s.iloc[i]
        out.iloc[i] = (v * k + out.iloc[i-1] * (1 - k)) if not np.isnan(v) else out.iloc[i-1]
    return out

def sma_ind(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()

def rsi_ind(series: pd.Series, period: int = 14) -> pd.Series:
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).reset_index(drop=True)

def rsi_ma_ind(rsi_series: pd.Series, period: int = 14) -> pd.Series:
    return sma_ind(rsi_series, period)

def ssf_ind(series: pd.Series, period: int) -> pd.Series:
    """Ehlers Super Smoother Filter (2-pole)."""
    import math
    s   = series.astype(float).reset_index(drop=True)
    out = pd.Series(np.nan, index=s.index)
    a   = math.exp(-math.sqrt(2) * math.pi / period)
    b   = 2 * a * math.cos(math.radians(math.sqrt(2) * 180 / period))
    c2  = b; c3 = -a * a; c1 = 1 - c2 - c3
    for i in range(len(s)):
        p0 = s.iloc[i]  if not np.isnan(s.iloc[i])  else 0.0
        p1 = s.iloc[i-1] if i >= 1 and not np.isnan(s.iloc[i-1]) else p0
        s1 = out.iloc[i-1] if i >= 1 and not np.isnan(out.iloc[i-1]) else p0
        s2 = out.iloc[i-2] if i >= 2 and not np.isnan(out.iloc[i-2]) else p0
        out.iloc[i] = c1 * (p0 + p1) / 2 + c2 * s1 + c3 * s2
    return out

def macd_ind(series: pd.Series, fast=12, slow=26, signal=9):
    ml  = ema_ind(series, fast) - ema_ind(series, slow)
    sig = ema_ind(ml.ffill(), signal)
    return ml, sig

def slope_ind(series: pd.Series, lookback: int = 3) -> pd.Series:
    return series.diff(lookback)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def sv(series, i):
    """Safe scalar value — returns float or None."""
    if i < 0 or i >= len(series):
        return None
    v = series.iloc[i] if isinstance(series, pd.Series) else series[i]
    return float(v) if (v == v) and v is not None and not (isinstance(v, float) and np.isnan(v)) else None

def make_trade(ticker, strategy, entry_date, entry_price, exit_date, exit_price):
    ep  = float(entry_price); xp = float(exit_price)
    pnl = round((xp - ep) / ep * 100, 2)
    return {
        "strategy":    strategy,
        "ticker":      ticker,
        "entry_date":  str(entry_date)[:10],
        "exit_date":   str(exit_date)[:10],
        "hold_days":   (pd.Timestamp(str(exit_date)[:10]) - pd.Timestamp(str(entry_date)[:10])).days,
        "entry_price": round(ep, 2),
        "exit_price":  round(xp, 2),
        "pnl_%":       pnl,
        "result":      "WIN" if pnl > 0 else "LOSS",
    }

# ─────────────────────────────────────────────────────────────────────────────
# STATISTICS
# ─────────────────────────────────────────────────────────────────────────────

def calc_stats(df: pd.DataFrame, label: str, period_years: float) -> dict:
    base = {"strategy": label, "trades": 0, "win_rate": 0, "wins": 0, "losses": 0,
            "avg_win": 0, "avg_loss": 0, "expectancy": 0, "total_return": 0,
            "cagr": 0, "max_dd": 0, "profit_factor": 0, "rr": 0,
            "avg_hold_days": 0, "score_old": 0, "score_v2": 0, "score_v3": 0}
    if df is None or len(df) == 0:
        return base
    t   = len(df)
    w   = int((df["pnl_%"] > 0).sum()); l = t - w
    wr  = round(w / t * 100, 1)
    aw  = round(df[df["pnl_%"] > 0]["pnl_%"].mean(), 2) if w else 0.0
    al  = round(df[df["pnl_%"] <= 0]["pnl_%"].mean(), 2) if l else 0.0
    exp = round(wr/100*aw + (1-wr/100)*al, 2)
    tot = round(df["pnl_%"].sum(), 2)
    gp  = df[df["pnl_%"] > 0]["pnl_%"].sum()
    gl  = abs(df[df["pnl_%"] <= 0]["pnl_%"].sum())
    pf  = round(gp / gl, 2) if gl > 0 else 999.0
    rr  = round(abs(aw / al), 2) if al != 0 else 0.0
    ah  = round(df["hold_days"].mean(), 1)
    cum = df.sort_values("exit_date")["pnl_%"].cumsum()
    dd  = round((cum - cum.cummax()).min(), 2)
    cagr = round(((1+tot/100)**(1/period_years)-1)*100, 2) if tot > -100 else -99.9
    da   = max(abs(dd), 1.0)
    return dict(
        strategy=label, trades=t, wins=w, losses=l, win_rate=wr,
        avg_win=aw, avg_loss=al, expectancy=exp, total_return=tot,
        cagr=cagr, max_dd=dd, profit_factor=pf, rr=rr, avg_hold_days=ah,
        score_old=round((exp*wr)/da, 3),
        score_v2=round((cagr*wr)/da, 3) if cagr > 0 else 0.0,
        score_v3=round((exp*wr*max(cagr,0))/(da**2), 3),
    )

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 1 — Monthly EMA20 Breakout
# ─────────────────────────────────────────────────────────────────────────────
# Universe  : NIFTY100_STOCKS — RSI>60 on D+W+M filters at bar time
# Setup     : EMA10 > EMA20 > EMA50 (monthly) AND close > EMA50
# Entry     : prev close < EMA20  AND  curr close > EMA20
# Exit      : EMA10 crosses below EMA20 (monthly) + both slopes < 0
# ─────────────────────────────────────────────────────────────────────────────

def backtest_s1(tickers, start, end):
    log.info(f"S1 Monthly EMA20 Breakout | Universe: {len(tickers)} Nifty100 stocks | {start} → {end}")
    trades = []; s_ts = pd.Timestamp(start); e_ts = pd.Timestamp(end)

    for ticker in tickers:
        data = fetch_multi(ticker, ("1d","1wk","1mo"))
        df_d = data["1d"]; df_w = data["1wk"]; df_m = data["1mo"]
        if any(x is None or len(x) < 40 for x in [df_d, df_w, df_m]):
            continue
        try:
            rsi_d_all = rsi_ind(df_d["close"], 14)
            rsi_w_all = rsi_ind(df_w["close"], 14)
            rsi_m_all = rsi_ind(df_m["close"], 14)
            e10_m     = ema_ind(df_m["close"], 10)
            e20_m     = ema_ind(df_m["close"], 20)
            e50_m     = ema_ind(df_m["close"], 50)
            sl10_m    = slope_ind(e10_m, 3)
            sl20_m    = slope_ind(e20_m, 3)
            close_m   = df_m["close"]
            dates_m   = df_m["date"]

            # Align daily + weekly RSI to monthly bar dates
            rsi_d_aligned = align_series_to_dates(dates_m, df_d, rsi_d_all)
            rsi_w_aligned = align_series_to_dates(dates_m, df_w, rsi_w_all)

            open_trade = None
            for i in range(2, len(close_m)):
                d    = dates_m.iloc[i]
                cn   = sv(close_m, i);  cp  = sv(close_m, i-1)
                e10  = sv(e10_m, i);    e10p = sv(e10_m, i-1)
                e20  = sv(e20_m, i);    e20p = sv(e20_m, i-1)
                e50  = sv(e50_m, i)
                sl10 = sv(sl10_m, i);   sl20 = sv(sl20_m, i)
                rd   = sv(rsi_d_aligned, i)   # daily RSI aligned to this month
                rw   = sv(rsi_w_aligned, i)   # weekly RSI aligned to this month
                rm   = sv(rsi_m_all, i)

                if None in (cn, cp, e10, e10p, e20, e20p, e50, rd, rw, rm):
                    continue

                if open_trade is None:
                    # ── Universe filter: RSI>60 on all 3 timeframes ──────────
                    if not (rd > 60 and rw > 60 and rm > 60):
                        continue
                    # ── Setup: EMA alignment + price above EMA50 ─────────────
                    setup_ok = (e10 > e20 > e50) and (cn > e50)
                    # ── Entry: price crosses above EMA20 this month ──────────
                    if setup_ok and (cp < e20p) and (cn > e20):
                        if s_ts <= d <= e_ts:
                            open_trade = (d, cn)
                else:
                    # ── Exit: EMA10 crosses below EMA20 + both slopes down ───
                    sell = (e10p > e20p) and (e10 < e20) and (sl10 or 0) < 0 and (sl20 or 0) < 0
                    if sell or d > e_ts:
                        trades.append(make_trade(ticker, "S1", open_trade[0], open_trade[1], d, cn))
                        open_trade = None

            if open_trade:
                ld = dates_m.iloc[-1]; lc = sv(close_m, len(close_m)-1)
                if lc and s_ts <= open_trade[0] <= e_ts:
                    trades.append(make_trade(ticker, "S1", open_trade[0], open_trade[1], ld, lc))

        except Exception as e:
            log.debug(f"S1 {ticker}: {e}")

    log.info(f"  → S1 complete: {len(trades)} trades")
    return pd.DataFrame(trades)

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 2 — Weekly EMA Pullback Cross
# ─────────────────────────────────────────────────────────────────────────────
# Universe  : NIFTY100_STOCKS — RSI14 > 60 on Daily AND Weekly AND Monthly
# Pre-cond  : EMA10 > EMA20 > EMA50 on monthly at time of weekly bar
# Setup     : Weekly EMA10 was below EMA20 last week (pullback in progress)
# Entry     : Weekly EMA10 crosses above EMA20 this week
# Exit      : Weekly EMA10 crosses below EMA20
# ─────────────────────────────────────────────────────────────────────────────

def backtest_s2(tickers, start, end):
    log.info(f"S2 Weekly EMA Pullback | Universe: {len(tickers)} Nifty100 stocks | {start} → {end}")
    trades = []; s_ts = pd.Timestamp(start); e_ts = pd.Timestamp(end)

    for ticker in tickers:
        data = fetch_multi(ticker, ("1d","1wk","1mo"))
        df_d = data["1d"]; df_w = data["1wk"]; df_m = data["1mo"]
        if any(x is None or len(x) < 26 for x in [df_d, df_w, df_m]):
            continue
        try:
            rsi_d_all = rsi_ind(df_d["close"], 14)
            rsi_w_all = rsi_ind(df_w["close"], 14)
            rsi_m_all = rsi_ind(df_m["close"], 14)
            e10_m     = ema_ind(df_m["close"], 10)
            e20_m     = ema_ind(df_m["close"], 20)
            e50_m     = ema_ind(df_m["close"], 50)
            e10_w     = ema_ind(df_w["close"], 10)
            e20_w     = ema_ind(df_w["close"], 20)
            close_w   = df_w["close"]
            dates_w   = df_w["date"]

            # Align daily + monthly RSI/EMAs to each weekly bar date
            rsi_d_aligned  = align_series_to_dates(dates_w, df_d, rsi_d_all)
            rsi_m_aligned  = align_series_to_dates(dates_w, df_m, rsi_m_all)
            e10_m_aligned  = align_series_to_dates(dates_w, df_m, e10_m)
            e20_m_aligned  = align_series_to_dates(dates_w, df_m, e20_m)
            e50_m_aligned  = align_series_to_dates(dates_w, df_m, e50_m)

            open_trade = None
            for i in range(2, len(close_w)):
                d    = dates_w.iloc[i]
                cn   = sv(close_w, i)
                e10n = sv(e10_w, i);    e10p = sv(e10_w, i-1)
                e20n = sv(e20_w, i);    e20p = sv(e20_w, i-1)
                rd   = sv(rsi_d_aligned, i)   # daily RSI as of this week's end date
                rw   = sv(rsi_w_all, i)
                rm   = sv(rsi_m_aligned, i)   # monthly RSI as of this week's end date
                me10 = sv(e10_m_aligned, i)
                me20 = sv(e20_m_aligned, i)
                me50 = sv(e50_m_aligned, i)

                if None in (cn, e10n, e10p, e20n, e20p, rd, rw, rm, me10, me20, me50):
                    continue

                if open_trade is None:
                    # ── Universe filter: RSI>60 all timeframes ───────────────
                    if not (rd > 60 and rw > 60 and rm > 60):
                        continue
                    # ── Monthly pre-condition: EMA10 > EMA20 > EMA50 ─────────
                    if not (me10 > me20 > me50):
                        continue
                    # ── Setup + Entry: EMA10 crosses above EMA20 from below ──
                    if (e10p < e20p) and (e10n > e20n) and s_ts <= d <= e_ts:
                        open_trade = (d, cn)
                else:
                    # ── Exit: EMA10 crosses below EMA20 (weekly) ────────────
                    if ((e10p > e20p) and (e10n < e20n)) or d > e_ts:
                        trades.append(make_trade(ticker, "S2", open_trade[0], open_trade[1], d, cn))
                        open_trade = None

            if open_trade:
                ld = dates_w.iloc[-1]; lc = sv(close_w, len(close_w)-1)
                if lc and s_ts <= open_trade[0] <= e_ts:
                    trades.append(make_trade(ticker, "S2", open_trade[0], open_trade[1], ld, lc))

        except Exception as e:
            log.debug(f"S2 {ticker}: {e}")

    log.info(f"  → S2 complete: {len(trades)} trades")
    return pd.DataFrame(trades)

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 3 — Monthly SSF50 Breakout  [Option C]
# ─────────────────────────────────────────────────────────────────────────────
# Universe  : DEFAULT_STOCKS — no indicator pre-filter (universe filter=NONE)
# Setup     : prev close < SSF50  AND  SSF200  AND  SSF250  (all three)
# Entry     : close crosses above SSF50
#             AND  RSI14 > RSI14_MA(14)
#             AND  MACD line > MACD signal
#             AND  MACD line > 0            [Option C gate]
# Exit      : MACD line crosses below MACD signal (monthly bearish crossover)
# ─────────────────────────────────────────────────────────────────────────────

def backtest_s3(tickers, start, end):
    log.info(f"S3 Monthly SSF50 [Opt-C] | Universe: {len(tickers)} stocks (no filter) | {start} → {end}")
    trades = []; s_ts = pd.Timestamp(start); e_ts = pd.Timestamp(end)

    for ticker in tickers:
        df_m = fetch(ticker, "1mo", years=9)
        if df_m is None or len(df_m) < 60:
            continue
        try:
            close_m = df_m["close"]; dates_m = df_m["date"]
            ssf50   = ssf_ind(close_m, 50)
            ssf200  = ssf_ind(close_m, 200)
            ssf250  = ssf_ind(close_m, 250)
            rsi14   = rsi_ind(close_m, 14)
            rsi14m  = rsi_ma_ind(rsi14, 14)
            ml, ms  = macd_ind(close_m)

            open_trade = None
            for i in range(2, len(close_m)):
                d      = dates_m.iloc[i]
                cn     = sv(close_m, i);   cp     = sv(close_m, i-1)
                s50n   = sv(ssf50, i);     s50p   = sv(ssf50, i-1)
                s200p  = sv(ssf200, i-1)
                s250p  = sv(ssf250, i-1)
                r      = sv(rsi14, i);     rma    = sv(rsi14m, i)
                mln    = sv(ml, i);        mlp    = sv(ml, i-1)
                msn    = sv(ms, i);        msp    = sv(ms, i-1)

                if None in (cn, cp, s50n, s50p, s200p, s250p, r, rma, mln, mlp, msn, msp):
                    continue

                if open_trade is None:
                    # ── Setup: prev close below all three SSF levels ──────────
                    setup = (cp < s50p) and (cp < s200p) and (cp < s250p)
                    if setup:
                        # ── Entry: breakout + RSI + MACD + MACD>0 ────────────
                        entry = ((cp < s50p) and (cn > s50n) and
                                 (r > rma) and (mln > msn) and (mln > 0))
                        if entry and s_ts <= d <= e_ts:
                            open_trade = (d, cn)
                else:
                    # ── Exit: MACD bearish crossover (was above, now below) ──
                    sell = (mlp > msp) and (mln < msn)
                    if sell or d > e_ts:
                        trades.append(make_trade(ticker, "S3", open_trade[0], open_trade[1], d, cn))
                        open_trade = None

            if open_trade:
                ld = dates_m.iloc[-1]; lc = sv(close_m, len(close_m)-1)
                if lc and s_ts <= open_trade[0] <= e_ts:
                    trades.append(make_trade(ticker, "S3", open_trade[0], open_trade[1], ld, lc))

        except Exception as e:
            log.debug(f"S3 {ticker}: {e}")

    log.info(f"  → S3 complete: {len(trades)} trades")
    return pd.DataFrame(trades)

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 4 — Weekly SSF50 Breakout  [Option D]
# ─────────────────────────────────────────────────────────────────────────────
# Universe  : DEFAULT_STOCKS — no indicator pre-filter (universe filter=NONE)
# Setup     : prev close < SSF50 ONLY  (SSF200+SSF250 not required — Opt D)
# Entry     : close crosses above SSF50
#             AND  RSI14 > RSI14_MA(14)
#             AND  MACD line > MACD signal
#             AND  MACD line > 0  AND  MACD signal > 0  (both positive)
# Exit      : MACD line crosses below MACD signal (weekly bearish crossover)
# ─────────────────────────────────────────────────────────────────────────────

def backtest_s4(tickers, start, end):
    log.info(f"S4 Weekly SSF50 [Opt-D]  | Universe: {len(tickers)} stocks (no filter) | {start} → {end}")
    trades = []; s_ts = pd.Timestamp(start); e_ts = pd.Timestamp(end)

    for ticker in tickers:
        df_w = fetch(ticker, "1wk", years=9)
        if df_w is None or len(df_w) < 60:
            continue
        try:
            close_w = df_w["close"]; dates_w = df_w["date"]
            ssf50   = ssf_ind(close_w, 50)
            rsi14   = rsi_ind(close_w, 14)
            rsi14m  = rsi_ma_ind(rsi14, 14)
            ml, ms  = macd_ind(close_w)

            open_trade = None
            for i in range(2, len(close_w)):
                d    = dates_w.iloc[i]
                cn   = sv(close_w, i);  cp  = sv(close_w, i-1)
                s50n = sv(ssf50, i);    s50p = sv(ssf50, i-1)
                r    = sv(rsi14, i);    rma = sv(rsi14m, i)
                mln  = sv(ml, i);       mlp = sv(ml, i-1)
                msn  = sv(ms, i);       msp = sv(ms, i-1)

                if None in (cn, cp, s50n, s50p, r, rma, mln, mlp, msn, msp):
                    continue

                if open_trade is None:
                    # ── Setup: prev close < SSF50 only (Option D) ────────────
                    setup = (cp < s50p)
                    if setup:
                        # ── Entry: SSF50 cross + RSI + MACD + both > 0 ───────
                        entry = ((cp < s50p) and (cn > s50n) and
                                 (r > rma) and
                                 (mln > msn) and (mln > 0) and (msn > 0))
                        if entry and s_ts <= d <= e_ts:
                            open_trade = (d, cn)
                else:
                    # ── Exit: MACD bearish crossover ─────────────────────────
                    sell = (mlp > msp) and (mln < msn)
                    if sell or d > e_ts:
                        trades.append(make_trade(ticker, "S4", open_trade[0], open_trade[1], d, cn))
                        open_trade = None

            if open_trade:
                ld = dates_w.iloc[-1]; lc = sv(close_w, len(close_w)-1)
                if lc and s_ts <= open_trade[0] <= e_ts:
                    trades.append(make_trade(ticker, "S4", open_trade[0], open_trade[1], ld, lc))

        except Exception as e:
            log.debug(f"S4 {ticker}: {e}")

    log.info(f"  → S4 complete: {len(trades)} trades")
    return pd.DataFrame(trades)

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 5 — Weekly ETF SSF50 Breakout  [Modified-1]
# ─────────────────────────────────────────────────────────────────────────────
# Universe  : ETF_TICKERS — all 13 ETFs, no pre-filter applied
# Setup     : prev close < SSF50
# Entry     : close crosses above SSF50
#             AND  RSI14 > RSI14_MA(14)   [Modified-1 confirmation gate]
# Exit      : NO EXIT CONDITION — this is a hold-forever strategy.
#             Every signal entered during the window is still open.
#             Exit date  = today (date the backtest is run)
#             Exit price = most recent weekly close available in yfinance data
#
# NOTE: Multiple entries per ETF are allowed — if the ETF re-crosses below
# SSF50 and then above again, a new entry fires. Each entry is independent
# and all are held to today. This reflects the real live system where you
# would hold all valid entries unless you manually close them.
# ─────────────────────────────────────────────────────────────────────────────

def backtest_s5(tickers, start, end):
    log.info(f"S5 ETF SSF50 [Mod-1]     | Universe: {len(tickers)} ETFs (no filter) | {start} → {end}")
    log.info(f"  S5 exit rule: NO exit condition — all trades held to today's price")
    trades = []
    s_ts = pd.Timestamp(start)
    e_ts = pd.Timestamp(end)
    today_str = TODAY  # date backtest is run — used as exit date for all S5 trades

    for ticker in tickers:
        df_w = fetch(ticker, "1wk", years=9)
        if df_w is None or len(df_w) < 60:
            continue
        try:
            close_w = df_w["close"]; dates_w = df_w["date"]
            ssf50   = ssf_ind(close_w, 50)
            rsi14   = rsi_ind(close_w, 14)
            rsi14m  = rsi_ma_ind(rsi14, 14)

            # Today's exit price = most recent close in the fetched data
            today_price = sv(close_w, len(close_w) - 1)
            today_date  = str(dates_w.iloc[-1])[:10]

            if today_price is None:
                continue

            # Track whether we are currently in a position to avoid
            # duplicate entries on the same uninterrupted run above SSF50.
            # A new entry is allowed only after price has reset below SSF50.
            in_position = False

            for i in range(2, len(close_w)):
                d    = dates_w.iloc[i]
                cn   = sv(close_w, i);  cp  = sv(close_w, i-1)
                s50n = sv(ssf50, i);    s50p = sv(ssf50, i-1)
                r    = sv(rsi14, i);    rma  = sv(rsi14m, i)

                if None in (cn, cp, s50n, s50p, r, rma):
                    continue

                # Reset position flag when price goes back below SSF50
                # (this does NOT close the trade — it just allows a new entry next time)
                if in_position and (cn < s50n):
                    in_position = False

                # ── Entry: SSF50 cross + RSI > RSI_MA + not already in position ──
                if (not in_position) and (cp < s50p) and (cn > s50n) and (r > rma):
                    if s_ts <= d <= e_ts:
                        # Trade entered — exits at today's price (no exit condition)
                        trades.append(make_trade(
                            ticker, "S5_ETF",
                            d, cn,
                            today_date, today_price,
                        ))
                        in_position = True

        except Exception as e:
            log.debug(f"S5 {ticker}: {e}")

    log.info(f"  → S5 complete: {len(trades)} trades  (all held open, exit = today {today_str})")
    return pd.DataFrame(trades)

# ─────────────────────────────────────────────────────────────────────────────
# HTML REPORT
# ─────────────────────────────────────────────────────────────────────────────

STRAT_COLORS = {
    "S1": "#7c83fd", "S2": "#00d68f",
    "S3": "#ffd700", "S4": "#ff9f43",
    "S5_ETF": "#ff6b6b", "ALL": "#a0a0a0",
}

def _color_pnl(v):  return "#00d68f" if v >= 0 else "#ff3d71"
def _color_dd(v):   return "#00d68f" if v > -20 else ("#ffd700" if v > -50 else "#ff3d71")

def _summary_rows_html(df):
    rows = ""
    for _, r in df.iterrows():
        if r.get("trades", 0) == 0:
            continue
        col = STRAT_COLORS.get(r["strategy"], "#aaa")
        rows += f"""<tr>
          <td style="color:{col};font-weight:700">{r['strategy']}</td>
          <td align="center">{r['trades']}</td>
          <td align="center" style="color:{_color_pnl(r['win_rate']-50)}">{r['win_rate']}%</td>
          <td align="center">{r['wins']}W / {r['losses']}L</td>
          <td style="color:{_color_pnl(r['avg_win'])}" align="right">{r['avg_win']:+.2f}%</td>
          <td style="color:{_color_pnl(r['avg_loss'])}" align="right">{r['avg_loss']:+.2f}%</td>
          <td style="color:{_color_pnl(r['expectancy'])};font-weight:700" align="right">{r['expectancy']:+.2f}%</td>
          <td style="color:#00b4d8;font-weight:700" align="right">{r['cagr']:+.2f}%</td>
          <td style="color:{_color_dd(r['max_dd'])}" align="right">{r['max_dd']:+.2f}%</td>
          <td align="right">{r['profit_factor']:.2f}</td>
          <td align="right">{r['rr']:.2f}</td>
          <td align="right">{r['avg_hold_days']:.0f}d</td>
          <td align="right">{r['score_old']:.2f}</td>
          <td align="right">{r['score_v2']:.2f}</td>
          <td style="color:#ffd700;font-weight:700" align="right">{r['score_v3']:.2f}</td>
        </tr>"""
    return rows

def _trade_rows_html(df, limit=300):
    rows = ""
    if df.empty:
        return rows
    for _, t in df.sort_values("entry_date", ascending=False).head(limit).iterrows():
        col = STRAT_COLORS.get(t["strategy"], "#aaa")
        rows += f"""<tr>
          <td style="color:{col}">{t['strategy']}</td>
          <td>{t['ticker']}</td>
          <td>{t['entry_date']}</td>
          <td>{t['exit_date']}</td>
          <td align="right">{t['hold_days']}d</td>
          <td align="right">₹{t['entry_price']:,.2f}</td>
          <td align="right">₹{t['exit_price']:,.2f}</td>
          <td style="color:{_color_pnl(t['pnl_%'])};font-weight:700" align="right">{t['pnl_%']:+.2f}%</td>
          <td style="color:{_color_pnl(t['pnl_%'])}">{t['result']}</td>
        </tr>"""
    return rows

def build_html(data_2020, data_2023):
    """
    data_2020 / data_2023 = dict with keys:
      'summary'    → pd.DataFrame
      'all_trades' → pd.DataFrame
    """
    def window_section(label, d):
        return f"""
<div class="section">
  <h2>{label}</h2>
  <div class="note">
    Scoring: <strong>Old</strong>=Exp×WR/|DD| &nbsp;·&nbsp;
    <strong>V2</strong>=CAGR×WR/|DD| &nbsp;·&nbsp;
    <strong>V3★</strong>=Exp×WR×CAGR/|DD|² (primary)
  </div>
  <table>
    <thead><tr>
      <th>Strategy</th><th>Trades</th><th>WR%</th><th>W / L</th>
      <th>Avg Win</th><th>Avg Loss</th><th>Expectancy</th>
      <th>CAGR%</th><th>MaxDD%</th><th>PF</th><th>R:R</th><th>Hold</th>
      <th>Old</th><th>V2</th><th>V3★</th>
    </tr></thead>
    <tbody>{_summary_rows_html(d['summary'])}</tbody>
  </table>
</div>
<div class="section">
  <h2>{label} — Trade Log (latest {min(300,len(d['all_trades']))} of {len(d['all_trades'])} trades)</h2>
  <table>
    <thead><tr>
      <th>Strategy</th><th>Ticker</th><th>Entry Date</th><th>Exit Date</th>
      <th>Hold</th><th>Entry ₹</th><th>Exit ₹</th><th>P&amp;L %</th><th>Result</th>
    </tr></thead>
    <tbody>{_trade_rows_html(d['all_trades'])}</tbody>
  </table>
</div>"""

    legend = "".join(
        f'<div class="leg"><div class="dot" style="background:{c}"></div><span>{s}</span></div>'
        for s, c in STRAT_COLORS.items() if s != "ALL"
    )

    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Nifty Quant System — Final Backtest</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0f1117;color:#e0e0e0;font-family:Inter,system-ui,sans-serif;
     padding:32px 44px;font-size:13px;line-height:1.6}}
h1{{color:#7c83fd;font-size:22px;font-weight:700;margin-bottom:4px}}
.meta{{color:#666;font-size:12px;margin-bottom:18px}}
h2{{color:#7c83fd;font-size:14px;font-weight:600;margin:22px 0 10px;
    padding-left:10px;border-left:3px solid #7c83fd}}
.section{{background:#13151f;border:1px solid #1e2130;border-radius:10px;
          padding:22px;margin-bottom:18px}}
.note{{background:#1a1d2e;border-left:3px solid #7c83fd;padding:9px 14px;
       border-radius:4px;font-size:11px;color:#bbb;margin-bottom:12px}}
.legend-grid{{background:#13151f;border:1px solid #1e2130;border-radius:10px;
              padding:20px 24px;margin-bottom:18px}}
.legend-grid h2{{margin:0 0 14px}}
.rules{{display:grid;grid-template-columns:repeat(5,1fr);gap:16px;margin-bottom:14px}}
.rule{{background:#0f1117;border:1px solid #1e2130;border-radius:8px;padding:14px}}
.rule-name{{font-weight:700;font-size:12px;margin-bottom:6px}}
.rule-row{{font-size:11px;color:#aaa;margin:3px 0}}
.rule-row strong{{color:#e0e0e0}}
.divider{{height:1px;background:#1e2130;margin:14px 0}}
.legend{{display:flex;gap:20px;flex-wrap:wrap}}
.leg{{display:flex;align-items:center;gap:6px;font-size:12px}}
.dot{{width:10px;height:10px;border-radius:50%;flex-shrink:0}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:#0f1117;color:#7c83fd;font-size:10px;text-transform:uppercase;
    letter-spacing:.7px;padding:7px 10px;border-bottom:2px solid #1e2130;white-space:nowrap}}
td{{padding:6px 10px;border-bottom:1px solid #1a1d2e;white-space:nowrap}}
tr:hover{{background:#1c1f2d}}
</style></head><body>

<h1>Nifty Quant System — Final Backtest Report</h1>
<div class="meta">All 5 strategies confirmed &nbsp;·&nbsp; Generated: {TODAY}</div>

<div class="legend-grid">
  <h2>Strategy Rules — Universe, Setup, Entry, Exit</h2>
  <div class="rules">

    <div class="rule">
      <div class="rule-name" style="color:#7c83fd">S1 — Monthly EMA20 Breakout</div>
      <div class="rule-row"><strong>Universe:</strong> All Nifty 100 stocks (100 stocks)</div>
      <div class="rule-row"><strong>Universe filter:</strong> RSI14 &gt; 60 on Daily AND Weekly AND Monthly</div>
      <div class="rule-row"><strong>Setup:</strong> EMA10 &gt; EMA20 &gt; EMA50 (monthly) AND close &gt; EMA50</div>
      <div class="rule-row"><strong>Entry:</strong> Price crosses above EMA20 (monthly)</div>
      <div class="rule-row"><strong>Exit:</strong> EMA10 crosses below EMA20 (monthly) + both slopes &lt; 0</div>
      <div class="rule-row"><strong>Timeframe:</strong> Monthly candles</div>
    </div>

    <div class="rule">
      <div class="rule-name" style="color:#00d68f">S2 — Weekly EMA Pullback</div>
      <div class="rule-row"><strong>Universe:</strong> All Nifty 100 stocks (100 stocks)</div>
      <div class="rule-row"><strong>Universe filter:</strong> RSI14 &gt; 60 on Daily AND Weekly AND Monthly</div>
      <div class="rule-row"><strong>Pre-cond:</strong> EMA10 &gt; EMA20 &gt; EMA50 on monthly</div>
      <div class="rule-row"><strong>Setup:</strong> Weekly EMA10 &lt; EMA20 last week (pullback)</div>
      <div class="rule-row"><strong>Entry:</strong> Weekly EMA10 crosses above EMA20</div>
      <div class="rule-row"><strong>Exit:</strong> Weekly EMA10 crosses below EMA20</div>
      <div class="rule-row"><strong>Timeframe:</strong> Weekly candles</div>
    </div>

    <div class="rule">
      <div class="rule-name" style="color:#ffd700">S3 — Monthly SSF50 Breakout [Opt-C]</div>
      <div class="rule-row"><strong>Universe:</strong> DEFAULT_STOCKS — no indicator pre-filter</div>
      <div class="rule-row"><strong>Setup:</strong> Prev close &lt; SSF50 AND SSF200 AND SSF250</div>
      <div class="rule-row"><strong>Entry:</strong> Close crosses above SSF50</div>
      <div class="rule-row">&nbsp;&nbsp;&nbsp;AND RSI14 &gt; RSI14_MA(14)</div>
      <div class="rule-row">&nbsp;&nbsp;&nbsp;AND MACD line &gt; signal</div>
      <div class="rule-row">&nbsp;&nbsp;&nbsp;AND MACD line &gt; 0 &nbsp;[Opt-C gate]</div>
      <div class="rule-row"><strong>Exit:</strong> MACD line crosses below signal (monthly)</div>
      <div class="rule-row"><strong>Timeframe:</strong> Monthly candles</div>
    </div>

    <div class="rule">
      <div class="rule-name" style="color:#ff9f43">S4 — Weekly SSF50 Breakout [Opt-D]</div>
      <div class="rule-row"><strong>Universe:</strong> DEFAULT_STOCKS — no indicator pre-filter</div>
      <div class="rule-row"><strong>Setup:</strong> Prev close &lt; SSF50 ONLY (SSF200+250 removed)</div>
      <div class="rule-row"><strong>Entry:</strong> Close crosses above SSF50</div>
      <div class="rule-row">&nbsp;&nbsp;&nbsp;AND RSI14 &gt; RSI14_MA(14)</div>
      <div class="rule-row">&nbsp;&nbsp;&nbsp;AND MACD line &gt; signal</div>
      <div class="rule-row">&nbsp;&nbsp;&nbsp;AND MACD line &gt; 0 AND signal &gt; 0</div>
      <div class="rule-row"><strong>Exit:</strong> MACD line crosses below signal (weekly)</div>
      <div class="rule-row"><strong>Timeframe:</strong> Weekly candles</div>
    </div>

    <div class="rule">
      <div class="rule-name" style="color:#ff6b6b">S5 — ETF SSF50 Breakout [Mod-1]</div>
      <div class="rule-row"><strong>Universe:</strong> 13 ETFs — no pre-filter applied</div>
      <div class="rule-row"><strong>Setup:</strong> Prev close &lt; SSF50</div>
      <div class="rule-row"><strong>Entry:</strong> Close crosses above SSF50</div>
      <div class="rule-row">&nbsp;&nbsp;&nbsp;AND RSI14 &gt; RSI14_MA(14) &nbsp;[Mod-1 gate]</div>
      <div class="rule-row"><strong>Exit:</strong> NO exit condition — held to today</div>
      <div class="rule-row"><strong>Exit price:</strong> Latest weekly close (date backtest is run)</div>
      <div class="rule-row"><strong>Timeframe:</strong> Weekly candles</div>
    </div>

  </div>
  <div class="divider"></div>
  <div class="legend">{legend}</div>
</div>

{window_section("📅 Window 1: 2023-01-01 → 2026-03-07 (Primary Validation)", data_2023)}
{window_section("📅 Window 2: 2020-01-01 → 2026-03-07 (Extended / Stress Test)", data_2020)}

<div class="section">
  <h2>Notes</h2>
  <div class="note">
    <strong>RSI alignment fix:</strong> Daily and monthly RSI values are date-matched to each
    weekly/monthly bar using forward-fill — not the naive last-value-in-series approach.
    This eliminates lookahead bias in S1 and S2.<br><br>
    <strong>S5 exit:</strong> No exit condition exists. Every S5 trade entered during the backtest window
    is held open. Exit date = today (date you run the backtest). Exit price = latest weekly close.
    CAGR and P&amp;L reflect the full unrealised gain from entry to today.<br><br>
    <strong>Universe note:</strong> S1 and S2 run on all Nifty 100 stocks. S3 and S4 run on
    the default 50-stock sample — pass <code>--universe nifty500.csv</code> to override for a full run.
  </div>
</div>

</body></html>"""

    fpath = OUT / "backtest_report_final.html"
    fpath.write_text(html, encoding="utf-8")
    return fpath

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

WINDOWS = [
    ("2020-01-01", "2026-03-07", 6.17),
    ("2023-01-01", "2026-03-07", 3.17),
]

def run_window(strategies, stock_tickers, start, end, years):
    results = {}
    if "S1" in strategies:
        results["S1"] = backtest_s1(NIFTY100_STOCKS, start, end)
        results["S1"].to_csv(OUT / f"s1_trades_{start[:4]}.csv", index=False)
    if "S2" in strategies:
        results["S2"] = backtest_s2(NIFTY100_STOCKS, start, end)
        results["S2"].to_csv(OUT / f"s2_trades_{start[:4]}.csv", index=False)
    if "S3" in strategies:
        results["S3"] = backtest_s3(stock_tickers, start, end)
        results["S3"].to_csv(OUT / f"s3_trades_{start[:4]}.csv", index=False)
    if "S4" in strategies:
        results["S4"] = backtest_s4(stock_tickers, start, end)
        results["S4"].to_csv(OUT / f"s4_trades_{start[:4]}.csv", index=False)
    if "S5" in strategies:
        results["S5_ETF"] = backtest_s5(ETF_TICKERS, start, end)
        results["S5_ETF"].to_csv(OUT / f"s5_trades_{start[:4]}.csv", index=False)

    all_dfs = [d for d in results.values() if not d.empty]
    all_trades = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    all_trades.to_csv(OUT / f"all_trades_{start[:4]}.csv", index=False)

    summary_rows = []
    for label, df in results.items():
        summary_rows.append(calc_stats(df, label, years))
    if not all_trades.empty:
        summary_rows.append(calc_stats(all_trades, "ALL", years))
    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(OUT / f"summary_{start[:4]}.csv", index=False)

    return {"summary": summary_df, "all_trades": all_trades}


def print_summary(label, data):
    log.info(f"\n{'═'*92}")
    log.info(f"  {label}")
    log.info(f"{'═'*92}")
    log.info(f"  {'Strategy':<12} {'Trades':>7} {'WR%':>7} {'Exp%':>9} "
             f"{'CAGR%':>9} {'MaxDD%':>9} {'PF':>7} {'R:R':>6} {'Hold':>7} {'V3★':>10}")
    log.info(f"  {'─'*92}")
    for _, r in data["summary"].iterrows():
        if r.get("trades", 0) == 0:
            log.info(f"  {r['strategy']:<12}  (0 trades)")
            continue
        log.info(
            f"  {r['strategy']:<12} {r['trades']:>7} {r['win_rate']:>7.1f} "
            f"{r['expectancy']:>+9.2f} {r['cagr']:>+9.2f} "
            f"{r['max_dd']:>+9.2f} {r['profit_factor']:>7.2f} "
            f"{r['rr']:>6.2f} {r['avg_hold_days']:>7.0f} {r['score_v3']:>10.3f}"
        )


def main():
    parser = argparse.ArgumentParser(description="Nifty Quant System — Final Backtest")
    parser.add_argument(
        "--strategies", nargs="+",
        default=["S1","S2","S3","S4","S5"],
        choices=["S1","S2","S3","S4","S5"],
        help="Which strategies to run (default: all five)",
    )
    parser.add_argument(
        "--universe", default=None,
        help="CSV with 'ticker' column — overrides DEFAULT_STOCKS for S1/S3/S4",
    )
    args = parser.parse_args()

    log.info(f"{'═'*60}")
    log.info(f"  Nifty Quant System — Final Backtest")
    log.info(f"  Strategies : {' '.join(args.strategies)}")
    log.info(f"  Windows    : 2020-2026  +  2023-2026")
    log.info(f"{'═'*60}")

    if args.universe:
        stock_tickers = pd.read_csv(args.universe)["ticker"].tolist()
        log.info(f"  Custom universe : {len(stock_tickers)} stocks from {args.universe}")
    else:
        stock_tickers = DEFAULT_STOCKS
        log.info(f"  Default universe: {len(stock_tickers)} stocks")
        log.info(f"  Tip: pass --universe nifty500.csv for full 500-stock run")

    data_by_window = {}
    for start, end, years in WINDOWS:
        log.info(f"\n{'─'*60}")
        log.info(f"  Running window: {start} → {end}")
        log.info(f"{'─'*60}")
        data_by_window[start[:4]] = run_window(args.strategies, stock_tickers, start, end, years)

    data_2020 = data_by_window["2020"]
    data_2023 = data_by_window["2023"]

    print_summary("RESULTS — 2023-01-01 → 2026-03-07  (Primary Window)", data_2023)
    print_summary("RESULTS — 2020-01-01 → 2026-03-07  (Extended / Stress Test)", data_2020)

    html_path = build_html(data_2020, data_2023)

    log.info(f"\n{'═'*60}")
    log.info(f"  Output files saved to:  {OUT.resolve()}")
    log.info(f"  summary_2020.csv / summary_2023.csv")
    log.info(f"  all_trades_2020.csv / all_trades_2023.csv")
    log.info(f"  s1/s2/s3/s4/s5_trades_2020.csv  (per strategy, 2020 window)")
    log.info(f"  s1/s2/s3/s4/s5_trades_2023.csv  (per strategy, 2023 window)")
    log.info(f"  backtest_report_final.html        (open in browser)")
    log.info(f"{'═'*60}\n")


if __name__ == "__main__":
    main()
