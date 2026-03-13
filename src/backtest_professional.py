"""
backtest_professional.py
========================
Professional-grade backtest for the Nifty 500 Quant Signal Engine.
Period: 2023-01-01 to 2026-03-07

POSITION SIZING
  Capital per trade : INR 50,000 (fixed position size)
  Max simultaneous  : 20 open positions shared across all strategies
  If slots full     : signal is skipped and logged, not queued
  Qty per trade     : floor(50000 / entry_price) shares
  Actual invested   : qty x entry_price

TRANSACTION COSTS (Zerodha equity delivery)
  Brokerage    : INR 20 flat per order leg = INR 40 round-trip
  STT          : 0.1% on sell-side turnover
  Exchange     : 0.00345% both legs (NSE)
  SEBI         : 0.0001% both legs
  GST          : 18% on brokerage + exchange + SEBI
  Stamp duty   : 0.015% on buy-side turnover

TAX (Indian equity delivery)
  STCG <1 year : 20% on gains
  LTCG >=1 yr  : 12.5% on gains above INR 1.25L exemption

REFERENCE CAPITAL : INR 10,00,000 (20 slots x INR 50,000)
  Used for CAGR, drawdown%, Sharpe, Sortino

OUTPUTS -> backtest_results_pro/
  trade_log.csv       every trade with all INR fields + costs + tax
  summary.csv         full metric table per strategy + ALL
  equity_curve.csv    daily portfolio value and drawdown
  tax_report.csv      per-trade STCG/LTCG breakdown
  skipped_signals.csv signals rejected when slots were full
  backtest_report.html  full visual HTML report

USAGE
  pip install yfinance pandas numpy
  python backtest_professional.py
  python backtest_professional.py --strategies S3 S4
  python backtest_professional.py --universe nifty500.csv
"""

import argparse
import logging
import math
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("bt_pro")

try:
    import yfinance as yf
except ImportError:
    log.error("Run: pip install yfinance pandas numpy")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────
POSITION_SIZE_INR = 50_000
MAX_POSITIONS     = 20
BROKERAGE_LEG     = 20.0
STT_SELL          = 0.001
EXCHANGE          = 0.0000345
SEBI              = 0.000001
GST               = 0.18
STAMP             = 0.00015
RISK_FREE         = 0.07
STCG_RATE         = 0.20
LTCG_RATE         = 0.125
LTCG_EXEMPT       = 125_000
START             = "2023-01-01"
END               = "2026-03-07"
PERIOD_YRS        = (pd.Timestamp(END) - pd.Timestamp(START)).days / 365.25
REF_CAP           = MAX_POSITIONS * POSITION_SIZE_INR
TODAY             = datetime.today().strftime("%Y-%m-%d")
OUT               = Path("backtest_results_pro")
OUT.mkdir(exist_ok=True)
BM_TICKER         = "^NSEI"

# Indicator warmup bars — skip the first N bars of the loop for each ticker
# to ensure all indicators (SSF50=50 bars, MACD=35 bars, RSI=14 bars) are stable.
# Using 100 weekly bars (~2 years of data) as a safe warmup for all strategies.
# Monthly strategies use 60 monthly bars (~5 years).
WARMUP_WEEKLY  = 100   # weekly strategies: S2, S4, S5
WARMUP_MONTHLY = 60    # monthly strategies: S1, S3

# SSF crossover buffer — yfinance and TradingView use slightly different adjusted
# price data for NSE stocks (dividend/split adjustments differ by ~0.3-0.8%).
# This causes SSF50 to be marginally lower in our backtest vs TradingView,
# producing false crossover signals. Requiring price > SSF * (1 + buffer)
# before calling a crossover eliminates these marginal/false entries.
SSF_BUFFER = 0.003    # 0.3% — price must be this % above SSF50 to confirm crossover

# ── Universe ──────────────────────────────────────────────────────────────────
NIFTY100 = [
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
    "ADANIPORTS.NS","ADANIGREEN.NS","AMBUJACEM.NS","AUROPHARMA.NS",
    "BAJAJHLDNG.NS","BANKBARODA.NS","BEL.NS","BERGEPAINT.NS","BOSCHLTD.NS",
    "CANBK.NS","CHOLAFIN.NS","COLPAL.NS","CONCOR.NS","DLF.NS","DMART.NS",
    "GAIL.NS","GODREJCP.NS","GODREJPROP.NS","HAL.NS","HAVELLS.NS",
    "HDFCLIFE.NS","INDUSTOWER.NS","IOC.NS","IRCTC.NS","JIOFIN.NS",
    "LICI.NS","LODHA.NS","LTF.NS","LTIM.NS","MOTHERSON.NS",
    "MRF.NS","NAUKRI.NS","NHPC.NS","NMDC.NS","OFSS.NS",
    "PAGEIND.NS","PETRONET.NS","PFC.NS","PNB.NS","RECLTD.NS",
    "SAIL.NS","SIEMENS.NS","SRF.NS","TORNTPHARM.NS","TRENT.NS",
    "UBL.NS","UNIONBANK.NS","VBL.NS","ZOMATO.NS","ZYDUSLIFE.NS",
]
DEFAULT50 = [
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
ETFS = [
    "NIFTYBEES.NS","JUNIORBEES.NS","SETFNIF50.NS",
    "BANKBEES.NS","AUTOBEES.NS","INFRABEES.NS","ITBEES.NS",
    "MON100.NS","GOLDBEES.NS","AIQ","ROBT","DTCR",
]

# ── Data fetch ────────────────────────────────────────────────────────────────
_cache = {}

def _fetch(ticker, interval, years=9):
    key = (ticker, interval)
    if key in _cache:
        return _cache[key]
    try:
        end = datetime.today()
        start = end - timedelta(days=365*(years+1))
        raw = yf.download(ticker, start=start, end=end,
                          interval=interval, auto_adjust=True, progress=False)
        if raw is None or len(raw) < 20:
            _cache[key] = None; return None
        raw = raw.reset_index()
        raw.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                       for c in raw.columns]
        dc = "datetime" if "datetime" in raw.columns else "date"
        raw = raw.rename(columns={dc: "date"})
        raw["date"] = pd.to_datetime(raw["date"]).dt.tz_localize(None)
        raw = raw[["date","close"]].dropna(subset=["close"]).reset_index(drop=True)
        _cache[key] = raw
    except Exception as exc:
        log.debug(f"fetch {ticker} {interval}: {exc}")
        _cache[key] = None
    return _cache[key]

def fetch(t, iv, yrs=9):    return _fetch(t, iv, yrs)
def fetchm(t, ivs=("1d","1wk","1mo"), yrs=9): return {iv: _fetch(t,iv,yrs) for iv in ivs}

def align(tgt_dates, src_df, src_series):
    sd = src_df["date"].values; sv2 = src_series.values
    out = np.full(len(tgt_dates), np.nan)
    for i, td in enumerate(tgt_dates):
        m = sd <= td
        if m.any(): out[i] = sv2[m][-1]
    return pd.Series(out, dtype=float)

# ── Indicators ────────────────────────────────────────────────────────────────
def ema(s, n):
    s = s.reset_index(drop=True).astype(float)
    out = pd.Series(np.nan, index=s.index)
    fv = s.first_valid_index()
    if fv is None or fv+n > len(s): return out
    out.iloc[fv+n-1] = s.iloc[fv:fv+n].mean()
    k = 2.0/(n+1)
    for i in range(fv+n, len(s)):
        v = s.iloc[i]
        out.iloc[i] = v*k + out.iloc[i-1]*(1-k) if not np.isnan(v) else out.iloc[i-1]
    return out

def sma(s, n): return s.rolling(n).mean()

def rsi(s, n=14):
    d = s.diff(); g = d.clip(lower=0); lo = (-d).clip(lower=0)
    ag = g.ewm(com=n-1, min_periods=n).mean()
    al = lo.ewm(com=n-1, min_periods=n).mean()
    rs = ag / al.replace(0, np.nan)
    return (100 - 100/(1+rs)).reset_index(drop=True)

def rsima(rs, n=14): return sma(rs, n)

def ssf(s, n):
    s = s.astype(float).reset_index(drop=True)
    out = pd.Series(np.nan, index=s.index)
    a = math.exp(-math.sqrt(2)*math.pi/n)
    b = 2*a*math.cos(math.radians(math.sqrt(2)*180/n))
    c2 = b; c3 = -a*a; c1 = 1-c2-c3
    for i in range(len(s)):
        p0 = s.iloc[i]   if not np.isnan(s.iloc[i])   else 0.0
        p1 = s.iloc[i-1] if i>=1 and not np.isnan(s.iloc[i-1]) else p0
        s1 = out.iloc[i-1] if i>=1 and not np.isnan(out.iloc[i-1]) else p0
        s2 = out.iloc[i-2] if i>=2 and not np.isnan(out.iloc[i-2]) else p0
        out.iloc[i] = c1*(p0+p1)/2 + c2*s1 + c3*s2
    return out

def macd(s, f=12, sl=26, sg=9):
    ml = ema(s,f) - ema(s,sl)
    return ml, ema(ml.ffill(), sg)

def slope(s, n=3): return s.diff(n)

def sv(s, i):
    if i < 0 or i >= len(s): return None
    v = s.iloc[i] if isinstance(s, pd.Series) else s[i]
    return float(v) if (v == v) and v is not None and not (isinstance(v,float) and np.isnan(v)) else None

# ── Costs & Tax ───────────────────────────────────────────────────────────────
def costs(ep, xp, qty):
    bt = ep*qty; st = xp*qty
    brok = BROKERAGE_LEG*2
    stt  = st*STT_SELL
    exch = (bt+st)*EXCHANGE
    sebi = (bt+st)*SEBI
    gst  = (brok+exch+sebi)*GST
    stmp = bt*STAMP
    tot  = brok+stt+exch+sebi+gst+stmp
    return dict(brokerage=round(brok,2), stt=round(stt,2),
                exchange_charges=round(exch,2), sebi_charges=round(sebi,2),
                gst=round(gst,2), stamp_duty=round(stmp,2),
                total_costs_inr=round(tot,2))

def tax(gross, days):
    if gross <= 0: return dict(tax_category="NIL", taxable_gain_inr=0.0, tax_inr=0.0)
    if days < 365: return dict(tax_category="STCG", taxable_gain_inr=round(gross,2),
                               tax_inr=round(gross*STCG_RATE,2))
    txbl = max(0.0, gross-LTCG_EXEMPT)
    return dict(tax_category="LTCG", taxable_gain_inr=round(txbl,2),
                tax_inr=round(txbl*LTCG_RATE,2))

# ── Position Manager ──────────────────────────────────────────────────────────
class PM:
    def __init__(self):
        self._open   = []
        self.closed  = []
        self.skipped = []
        self._ctr    = 0

    @property
    def free(self): return MAX_POSITIONS - len(self._open)

    def open(self, strat, ticker, entry_date, entry_price):
        if self.free == 0:
            self.skipped.append(dict(strategy=strat, ticker=ticker,
                                     entry_date=str(entry_date)[:10],
                                     entry_price=round(float(entry_price),2),
                                     reason="slots_full"))
            return None
        ep  = float(entry_price)
        qty = max(1, int(POSITION_SIZE_INR // ep))
        self._ctr += 1
        t = dict(trade_id=f"{strat}_{ticker}_{str(entry_date)[:10]}",
                 strategy=strat, ticker=ticker,
                 entry_date=str(entry_date)[:10],
                 entry_price=round(ep,2), qty=qty,
                 invested_inr=round(qty*ep,2),
                 slot_no=self._ctr, status="OPEN")
        self._open.append(t)
        return t

    def close(self, ticker, strat, exit_date, exit_price):
        for t in self._open:
            if t["ticker"]==ticker and t["strategy"]==strat:
                self._open.remove(t); t = dict(t)
                xp = float(exit_price)
                t["exit_date"]  = str(exit_date)[:10]
                t["exit_price"] = round(xp,2)
                t["hold_days"]  = (pd.Timestamp(t["exit_date"])-pd.Timestamp(t["entry_date"])).days
                t["status"]     = "CLOSED"
                gross = round((xp-t["entry_price"])*t["qty"],2)
                pct   = round((xp-t["entry_price"])/t["entry_price"]*100,2)
                c     = costs(t["entry_price"],xp,t["qty"])
                net   = round(gross-c["total_costs_inr"],2)
                npct  = round(net/t["invested_inr"]*100,2)
                tx    = tax(gross, t["hold_days"])
                t.update(dict(gross_pnl_inr=gross, pnl_pct=pct,
                              net_pnl_inr=net, net_pnl_pct=npct,
                              result="WIN" if net>0 else "LOSS", **c, **tx))
                self.closed.append(t)
                return t
        return None

    def force_close_all(self, exit_date, price_map):
        for t in list(self._open):
            px = price_map.get(t["ticker"])
            if px: self.close(t["ticker"],t["strategy"],exit_date,px)

    def closed_df(self):  return pd.DataFrame(self.closed)  if self.closed  else pd.DataFrame()
    def skipped_df(self): return pd.DataFrame(self.skipped) if self.skipped else pd.DataFrame()

# ── Strategy runners ──────────────────────────────────────────────────────────
def run_s1(pm, tickers, s, e):
    log.info(f"S1  Monthly EMA20 Breakout  |  {len(tickers)} stocks")
    st = pd.Timestamp(s); et = pd.Timestamp(e)
    for tk in tickers:
        d = fetchm(tk)
        dd,dw,dm = d["1d"],d["1wk"],d["1mo"]
        if any(x is None or len(x)<40 for x in [dd,dw,dm]): continue
        try:
            rd=rsi(dd["close"],14); rw=rsi(dw["close"],14); rm=rsi(dm["close"],14)
            e10=ema(dm["close"],10); e20=ema(dm["close"],20); e50=ema(dm["close"],50)
            sl10=slope(e10,3); sl20=slope(e20,3)
            rda=align(dm["date"],dd,rd); rwa=align(dm["date"],dw,rw)
            cl=dm["close"]; dt=dm["date"]; inp=False
            for i in range(2,len(cl)):
                if i < WARMUP_MONTHLY: continue   # wait for indicators to warm up
                bd=dt.iloc[i]
                cn,cp=sv(cl,i),sv(cl,i-1)
                e10n,e10p=sv(e10,i),sv(e10,i-1)
                e20n,e20p=sv(e20,i),sv(e20,i-1)
                e50n=sv(e50,i); s10=sv(sl10,i); s20=sv(sl20,i)
                rdi=sv(rda,i); rwi=sv(rwa,i); rmi=sv(rm,i)
                if None in (cn,cp,e10n,e10p,e20n,e20p,e50n,rdi,rwi,rmi): continue
                if not inp:
                    if not (rdi>60 and rwi>60 and rmi>60): continue
                    if (e10n>e20n>e50n) and (cn>e50n) and (cp<e20p) and (cn>e20n):
                        if st<=bd<=et:
                            inp=True          # always set — prevents re-attempt if slots full
                            pm.open("S1",tk,bd,cn)
                else:
                    if ((e10p>e20p) and (e10n<e20n) and (s10 or 0)<0 and (s20 or 0)<0) or bd>et:
                        pm.close(tk,"S1",bd,cn); inp=False
            if inp: pm.close(tk,"S1",dt.iloc[-1],sv(cl,len(cl)-1))
        except Exception as exc: log.debug(f"S1 {tk}: {exc}")

def run_s2(pm, tickers, s, e):
    log.info(f"S2  Weekly EMA Pullback     |  {len(tickers)} stocks")
    st = pd.Timestamp(s); et = pd.Timestamp(e)
    for tk in tickers:
        d = fetchm(tk)
        dd,dw,dm = d["1d"],d["1wk"],d["1mo"]
        if any(x is None or len(x)<26 for x in [dd,dw,dm]): continue
        try:
            rd=rsi(dd["close"],14); rw=rsi(dw["close"],14); rm=rsi(dm["close"],14)
            me10=ema(dm["close"],10); me20=ema(dm["close"],20); me50=ema(dm["close"],50)
            we10=ema(dw["close"],10); we20=ema(dw["close"],20)
            dtw=dw["date"]; clw=dw["close"]
            rda=align(dtw,dd,rd); rma2=align(dtw,dm,rm)
            m10a=align(dtw,dm,me10); m20a=align(dtw,dm,me20); m50a=align(dtw,dm,me50)
            inp=False
            for i in range(2,len(clw)):
                if i < WARMUP_WEEKLY: continue    # wait for EMA/RSI indicators to warm up
                bd=dtw.iloc[i]; cn=sv(clw,i)
                e10n,e10p=sv(we10,i),sv(we10,i-1)
                e20n,e20p=sv(we20,i),sv(we20,i-1)
                rdi=sv(rda,i); rwi=sv(rw,i); rmi=sv(rma2,i)
                m10=sv(m10a,i); m20=sv(m20a,i); m50=sv(m50a,i)
                if None in (cn,e10n,e10p,e20n,e20p,rdi,rwi,rmi,m10,m20,m50): continue
                if not inp:
                    if not (rdi>60 and rwi>60 and rmi>60): continue
                    if not (m10>m20>m50): continue
                    if (e10p<e20p) and (e10n>e20n) and st<=bd<=et:
                        inp=True          # always set — prevents re-attempt if slots full
                        pm.open("S2",tk,bd,cn)
                else:
                    if ((e10p>e20p) and (e10n<e20n)) or bd>et:
                        pm.close(tk,"S2",bd,cn); inp=False
            if inp: pm.close(tk,"S2",dtw.iloc[-1],sv(clw,len(clw)-1))
        except Exception as exc: log.debug(f"S2 {tk}: {exc}")

def run_s3(pm, tickers, s, e):
    log.info(f"S3  Monthly SSF50 [Opt-C]   |  {len(tickers)} stocks")
    st = pd.Timestamp(s); et = pd.Timestamp(e)
    for tk in tickers:
        dm = fetch(tk,"1mo",9)
        if dm is None or len(dm)<60: continue
        try:
            cl=dm["close"]; dt=dm["date"]
            sf50=ssf(cl,50); sf200=ssf(cl,200); sf250=ssf(cl,250)
            ri=rsi(cl,14); rim=rsima(ri,14); ml,ms=macd(cl)
            inp=False
            for i in range(2,len(cl)):
                if i < WARMUP_MONTHLY: continue   # wait for SSF50/200/250 + MACD to warm up
                bd=dt.iloc[i]; cn,cp=sv(cl,i),sv(cl,i-1)
                s50n,s50p=sv(sf50,i),sv(sf50,i-1)
                s200p=sv(sf200,i-1); s250p=sv(sf250,i-1)
                r,rm=sv(ri,i),sv(rim,i)
                mln,mlp=sv(ml,i),sv(ml,i-1); msn,msp=sv(ms,i),sv(ms,i-1)
                if None in (cn,cp,s50n,s50p,s200p,s250p,r,rm,mln,mlp,msn,msp): continue
                if not inp:
                    # Setup: prev close below ALL three SSF levels
                    if (cp<s50p) and (cp<s200p) and (cp<s250p):
                        # Entry: breakout above SSF50 + MACD + RSI confirmation
                        if (cn > s50n*(1+SSF_BUFFER)) and (r>rm) and (mln>msn) and (mln>0):
                            if st<=bd<=et:
                                inp=True          # always set — prevents re-attempt if slots full
                                pm.open("S3",tk,bd,cn)
                else:
                    if ((mlp>msp) and (mln<msn)) or bd>et:
                        pm.close(tk,"S3",bd,cn); inp=False
            if inp: pm.close(tk,"S3",dt.iloc[-1],sv(cl,len(cl)-1))
        except Exception as exc: log.debug(f"S3 {tk}: {exc}")

def run_s4(pm, tickers, s, e):
    log.info(f"S4  Weekly SSF50 [Opt-D]    |  {len(tickers)} stocks")
    st = pd.Timestamp(s); et = pd.Timestamp(e)
    for tk in tickers:
        dw = fetch(tk,"1wk",9)
        if dw is None or len(dw)<60: continue
        try:
            cl=dw["close"]; dt=dw["date"]
            sf50=ssf(cl,50); ri=rsi(cl,14); rim=rsima(ri,14); ml,ms=macd(cl)
            inp=False
            below_ssf = True  # tracks whether price has been below SSF50 since last exit
            for i in range(2,len(cl)):
                if i < WARMUP_WEEKLY: continue    # wait for SSF50/MACD/RSI to warm up
                bd=dt.iloc[i]; cn,cp=sv(cl,i),sv(cl,i-1)
                s50n,s50p=sv(sf50,i),sv(sf50,i-1)
                r,rm=sv(ri,i),sv(rim,i)
                mln,mlp=sv(ml,i),sv(ml,i-1); msn,msp=sv(ms,i),sv(ms,i-1)
                if None in (cn,cp,s50n,s50p,r,rm,mln,mlp,msn,msp): continue
                # Track when price drops below SSF50 — required before any re-entry
                if not inp and cn < s50n:
                    below_ssf = True
                if not inp:
                    # Entry: price must have been below SSF50 (below_ssf=True) AND
                    # previous close < SSF50 AND current close > SSF50 (the actual crossover)
                    if below_ssf and (cp<s50p) and (cn > s50n*(1+SSF_BUFFER)) and (r>rm) and (mln>msn) and (mln>0) and (msn>0):
                        if st<=bd<=et:
                            inp=True; below_ssf=False  # reset: must go below SSF50 again before next entry
                            pm.open("S4",tk,bd,cn)
                else:
                    if ((mlp>msp) and (mln<msn)) or bd>et:
                        pm.close(tk,"S4",bd,cn); inp=False
                        # below_ssf stays False — price must go below SSF50 before re-entry
            if inp: pm.close(tk,"S4",dt.iloc[-1],sv(cl,len(cl)-1))
        except Exception as exc: log.debug(f"S4 {tk}: {exc}")


def run_s5(pm, tickers, s, e):
    log.info(f"S5  ETF SSF50 [Mod-1]       |  {len(tickers)} ETFs  (held to today)")
    st = pd.Timestamp(s); et = pd.Timestamp(e)
    for tk in tickers:
        dw = fetch(tk,"1wk",9)
        if dw is None or len(dw)<60: continue
        try:
            cl=dw["close"]; dt=dw["date"]
            sf50=ssf(cl,50); ri=rsi(cl,14); rim=rsima(ri,14)
            todpx=sv(cl,len(cl)-1); toddt=str(dt.iloc[-1])[:10]
            if todpx is None: continue
            inp=False
            for i in range(2,len(cl)):
                if i < WARMUP_WEEKLY: continue    # wait for SSF50/RSI to warm up
                bd=dt.iloc[i]; cn,cp=sv(cl,i),sv(cl,i-1)
                s50n,s50p=sv(sf50,i),sv(sf50,i-1)
                r,rm=sv(ri,i),sv(rim,i)
                if None in (cn,cp,s50n,s50p,r,rm): continue
                if inp and cn<s50n: inp=False
                if (not inp) and (cp<s50p) and (cn > s50n*(1+SSF_BUFFER)) and (r>rm):
                    if st<=bd<=et:
                        inp=True          # always set — prevents re-attempt if slots full
                        if pm.open("S5",tk,bd,cn):
                            pm.close(tk,"S5",toddt,todpx)
        except Exception as exc: log.debug(f"S5 {tk}: {exc}")

# ── Benchmark ─────────────────────────────────────────────────────────────────
def get_benchmark():
    try:
        df = fetch(BM_TICKER,"1d",5)
        if df is None or df.empty: return {}
        df = df[(df["date"]>=pd.Timestamp(START)) & (df["date"]<=pd.Timestamp(END))].reset_index(drop=True)
        if len(df)<10: return {}
        sp=df["close"].iloc[0]; ep=df["close"].iloc[-1]
        yrs=(df["date"].iloc[-1]-df["date"].iloc[0]).days/365.25
        ret=(ep/sp-1)*100
        cagr=((ep/sp)**(1/yrs)-1)*100 if yrs>0 else 0
        dr=df["close"].pct_change().dropna()
        vol=dr.std()*np.sqrt(252)*100
        mdd=((df["close"]-df["close"].cummax())/df["close"].cummax()*100).min()
        return dict(name="Nifty 50 (^NSEI)",
                    return_pct=round(ret,2), cagr_pct=round(cagr,2),
                    vol_pct=round(vol,2), maxdd_pct=round(mdd,2),
                    _dr=dr, _prices=df.set_index("date")["close"])
    except Exception as exc:
        log.debug(f"benchmark: {exc}"); return {}

# ── Equity curve ──────────────────────────────────────────────────────────────
def equity_curve(trades, s, e):
    dr = pd.date_range(start=s, end=e, freq="D")
    daily = pd.Series(0.0, index=dr)
    if not trades.empty:
        for d_str,v in trades.groupby("exit_date")["net_pnl_inr"].sum().items():
            ts = pd.Timestamp(d_str)
            if ts in daily.index: daily[ts] = v
    cum  = daily.cumsum()
    peak = cum.cummax()
    ddinr= cum - peak
    ddpct= (ddinr/REF_CAP*100).round(4)
    return pd.DataFrame({
        "date":                dr.strftime("%Y-%m-%d"),
        "daily_pnl_inr":       daily.values.round(2),
        "cumulative_pnl_inr":  cum.values.round(2),
        "portfolio_value_inr": (REF_CAP+cum).values.round(2),
        "drawdown_pct":        ddpct.values,
        "drawdown_inr":        ddinr.values.round(2),
    })

# ── Full analytics ────────────────────────────────────────────────────────────
def analytics(label, trades, eq, bm):
    row = {"strategy": label}
    ZERO = ["trades","wins","losses","win_rate_pct","avg_win_pct","avg_loss_pct",
            "best_trade_pct","worst_trade_pct","best_trade_inr","worst_trade_inr",
            "avg_hold_days","median_hold_days","max_hold_days","min_hold_days",
            "expectancy_pct","expectancy_inr","profit_factor","rr_ratio",
            "total_deployed_inr","gross_pnl_inr","total_costs_inr","net_pnl_inr",
            "net_pnl_pct_on_deployed","total_return_pct","cagr_pct",
            "volatility_ann_pct","downside_vol_pct","sharpe","sortino","calmar",
            "max_drawdown_pct","max_drawdown_inr","longest_drawdown_days",
            "var_95_pct","cvar_95_pct","stcg_tax_inr","ltcg_tax_inr",
            "total_tax_inr","net_after_tax_inr","alpha_pct","beta",
            "information_ratio","score_old","score_v2","score_v3"]
    for k in ZERO: row[k] = 0
    if trades is None or trades.empty: return row

    df=trades.copy(); t=len(df)
    w=int((df["net_pnl_inr"]>0).sum()); l=t-w; wr=round(w/t*100,1)
    wdf=df[df["net_pnl_inr"]>0]; ldf=df[df["net_pnl_inr"]<=0]
    awp=round(wdf["pnl_pct"].mean(),2) if w else 0.0
    alp=round(ldf["pnl_pct"].mean(),2) if l else 0.0
    awi=round(wdf["net_pnl_inr"].mean(),2) if w else 0.0
    ali=round(ldf["net_pnl_inr"].mean(),2) if l else 0.0
    expp=round(wr/100*awp+(1-wr/100)*alp,2)
    expi=round(wr/100*awi+(1-wr/100)*ali,2)
    gp=wdf["net_pnl_inr"].sum(); gl=abs(ldf["net_pnl_inr"].sum())
    pf=round(gp/gl,2) if gl>0 else 999.0
    rr=round(abs(awi/ali),2) if ali!=0 else 0.0
    tdep=round(df["invested_inr"].sum(),2)
    gpnl=round(df["gross_pnl_inr"].sum(),2)
    tcst=round(df["total_costs_inr"].sum(),2)
    npnl=round(df["net_pnl_inr"].sum(),2)
    ndpc=round(npnl/tdep*100,2) if tdep>0 else 0.0
    tret=round(npnl/REF_CAP*100,2)
    cagr=round(((1+tret/100)**(1/PERIOD_YRS)-1)*100,2) if tret>-100 else -99.9
    av=dv=mddp=mddi=ldd=v95=cv95=0.0
    if not eq.empty:
        dr2=pd.Series(eq["daily_pnl_inr"].values)/REF_CAP
        if len(dr2)>20:
            av=round(dr2.std()*np.sqrt(252)*100,2)
            neg=dr2[dr2<0]; dv=round(neg.std()*np.sqrt(252)*100,2) if len(neg)>2 else 0.0
            v95=round(float(np.percentile(dr2,5))*100,2)
            cv95=round(float(dr2[dr2<=np.percentile(dr2,5)].mean())*100,2)
        dds=pd.Series(eq["drawdown_pct"].values)
        mddp=round(float(dds.min()),2)
        mddi=round(float(pd.Series(eq["drawdown_inr"].values).min()),2)
        ind=False; ds=0; ml=0
        for i,v in enumerate(dds):
            if v<0:
                if not ind: ds=i; ind=True
                ml=max(ml,i-ds+1)
            else: ind=False
        ldd=ml
    da=max(abs(mddp),0.01)
    sh=round((cagr-RISK_FREE*100)/av,2)  if av>0 else 0.0
    so=round((cagr-RISK_FREE*100)/dv,2)  if dv>0 else 0.0
    ca=round(cagr/da,2)
    stcg=round(df[df["tax_category"]=="STCG"]["tax_inr"].sum(),2) if "tax_category" in df.columns else 0.0
    ltcg=round(df[df["tax_category"]=="LTCG"]["tax_inr"].sum(),2) if "tax_category" in df.columns else 0.0
    ttax=round(stcg+ltcg,2); afttx=round(npnl-ttax,2)
    alpha=beta=ir=0.0
    if bm:
        alpha=round(cagr-bm.get("cagr_pct",0),2)
        bdr=bm.get("_dr",pd.Series(dtype=float))
        if not eq.empty and len(bdr)>20:
            sdr=pd.Series(eq["daily_pnl_inr"].values/REF_CAP,
                          index=pd.to_datetime(eq["date"]))
            cm=sdr.index.intersection(bdr.index)
            if len(cm)>20:
                sv3=sdr[cm]; bv=bdr[cm]
                vb=np.var(bv)
                beta=round(np.cov(sv3,bv)[0][1]/vb,2) if vb>0 else 0.0
                te=(sv3-bv).std()*np.sqrt(252)*100
                ir=round(alpha/te,2) if te>0 else 0.0
    sold=round(expp*wr/da,3); sv2c=round(cagr*wr/da,3) if cagr>0 else 0.0
    sv3c=round(expp*wr*max(cagr,0)/da**2,3)
    row.update(dict(
        trades=t, wins=w, losses=l, win_rate_pct=wr,
        avg_win_pct=awp, avg_loss_pct=alp,
        best_trade_pct=round(df["pnl_pct"].max(),2),
        worst_trade_pct=round(df["pnl_pct"].min(),2),
        best_trade_inr=round(df["net_pnl_inr"].max(),2),
        worst_trade_inr=round(df["net_pnl_inr"].min(),2),
        avg_hold_days=round(df["hold_days"].mean(),1),
        median_hold_days=round(df["hold_days"].median(),1),
        max_hold_days=int(df["hold_days"].max()),
        min_hold_days=int(df["hold_days"].min()),
        expectancy_pct=expp, expectancy_inr=expi,
        profit_factor=pf, rr_ratio=rr,
        total_deployed_inr=tdep, gross_pnl_inr=gpnl,
        total_costs_inr=tcst, net_pnl_inr=npnl,
        net_pnl_pct_on_deployed=ndpc,
        total_return_pct=tret, cagr_pct=cagr,
        volatility_ann_pct=av, downside_vol_pct=dv,
        sharpe=sh, sortino=so, calmar=ca,
        max_drawdown_pct=mddp, max_drawdown_inr=mddi,
        longest_drawdown_days=ldd,
        var_95_pct=v95, cvar_95_pct=cv95,
        stcg_tax_inr=stcg, ltcg_tax_inr=ltcg,
        total_tax_inr=ttax, net_after_tax_inr=afttx,
        alpha_pct=alpha, beta=beta, information_ratio=ir,
        score_old=sold, score_v2=sv2c, score_v3=sv3c,
    ))
    return row

# ── HTML Report ───────────────────────────────────────────────────────────────
COLS = {"S1":"#3B82F6","S2":"#10B981","S3":"#F59E0B","S4":"#EF4444","S5":"#8B5CF6","ALL":"#94A3B8"}

def pc(v, n=0): return "#16A34A" if float(v)>n else "#DC2626"
def ddc(v):     return "#16A34A" if float(v)>-15 else ("#D97706" if float(v)>-30 else "#DC2626")

def html_summary_rows(df):
    out=""
    for _,r in df.iterrows():
        if r.get("trades",0)==0: continue
        c=COLS.get(r["strategy"],"#666")
        out+=f"""<tr>
<td><b style="color:{c}">{r['strategy']}</b></td>
<td class=n>{r['trades']}</td>
<td class=n style="color:{pc(r['win_rate_pct']-50)}">{r['win_rate_pct']:.1f}%</td>
<td class=n>{r['wins']}W/{r['losses']}L</td>
<td class=n style="color:{pc(r['avg_win_pct'])}">{r['avg_win_pct']:+.2f}%</td>
<td class=n style="color:{pc(r['avg_loss_pct'])}">{r['avg_loss_pct']:+.2f}%</td>
<td class=n style="color:{pc(r['expectancy_pct'])};font-weight:700">{r['expectancy_pct']:+.2f}%</td>
<td class=n>&#8377;{r['expectancy_inr']:,.0f}</td>
<td class=n>{r['profit_factor']:.2f}</td>
<td class=n>{r['rr_ratio']:.2f}</td>
<td class=n>{r['avg_hold_days']:.0f}d</td>
<td class=n>{r['median_hold_days']:.0f}d</td>
<td class=n>{r['max_hold_days']}d/{r['min_hold_days']}d</td>
<td class=n style="color:{pc(r['best_trade_pct'])}">{r['best_trade_pct']:+.1f}%</td>
<td class=n style="color:{pc(r['worst_trade_pct'])}">{r['worst_trade_pct']:+.1f}%</td>
</tr>"""
    return out

def html_return_rows(df, bm):
    out=""; bmc=bm.get("cagr_pct",0) if bm else 0
    for _,r in df.iterrows():
        if r.get("trades",0)==0: continue
        c=COLS.get(r["strategy"],"#666")
        out+=f"""<tr>
<td><b style="color:{c}">{r['strategy']}</b></td>
<td class=n style="color:{pc(r['total_return_pct'])}">{r['total_return_pct']:+.2f}%</td>
<td class=n style="color:{pc(r['cagr_pct'])};font-weight:700">{r['cagr_pct']:+.2f}%</td>
<td class=n style="color:{pc(r['net_pnl_inr'])};font-weight:700">&#8377;{r['net_pnl_inr']:,.0f}</td>
<td class=n>&#8377;{r['gross_pnl_inr']:,.0f}</td>
<td class=n style="color:#DC2626">&#8377;{r['total_costs_inr']:,.0f}</td>
<td class=n>&#8377;{r['total_deployed_inr']:,.0f}</td>
<td class=n>{r['net_pnl_pct_on_deployed']:+.2f}%</td>
<td class=n style="color:{ddc(r['max_drawdown_pct'])}">{r['max_drawdown_pct']:+.2f}%</td>
<td class=n>&#8377;{abs(r['max_drawdown_inr']):,.0f}</td>
<td class=n>{r['longest_drawdown_days']}d</td>
<td class=n>{r['volatility_ann_pct']:.2f}%</td>
<td class=n style="color:{pc(r['sharpe'])}">{r['sharpe']:.2f}</td>
<td class=n style="color:{pc(r['sortino'])}">{r['sortino']:.2f}</td>
<td class=n style="color:{pc(r['calmar'])}">{r['calmar']:.2f}</td>
<td class=n>{r['var_95_pct']:+.2f}%</td>
<td class=n>{r['cvar_95_pct']:+.2f}%</td>
<td class=n style="color:{pc(r['alpha_pct'])}">{r['alpha_pct']:+.2f}%</td>
<td class=n>{r['beta']:.2f}</td>
<td class=n>{r['information_ratio']:.2f}</td>
</tr>"""
    return out, bmc

def html_tax_rows(df):
    out=""
    for _,r in df.iterrows():
        if r.get("trades",0)==0: continue
        c=COLS.get(r["strategy"],"#666")
        tax_pct = r['total_tax_inr']/max(abs(r['net_pnl_inr']),1)*100
        out+=f"""<tr>
<td><b style="color:{c}">{r['strategy']}</b></td>
<td class=n>&#8377;{r['net_pnl_inr']:,.0f}</td>
<td class=n>&#8377;{r['stcg_tax_inr']:,.0f}</td>
<td class=n>&#8377;{r['ltcg_tax_inr']:,.0f}</td>
<td class=n style="color:#DC2626">&#8377;{r['total_tax_inr']:,.0f}</td>
<td class=n style="color:{pc(r['net_after_tax_inr'])};font-weight:700">&#8377;{r['net_after_tax_inr']:,.0f}</td>
<td class=n style="color:#D97706">{tax_pct:.1f}%</td>
</tr>"""
    return out

def html_score_rows(df):
    out=""
    for _,r in df.iterrows():
        if r.get("trades",0)==0: continue
        c=COLS.get(r["strategy"],"#666")
        out+=f"""<tr>
<td><b style="color:{c}">{r['strategy']}</b></td>
<td class=n>{r['expectancy_pct']:+.2f}%</td>
<td class=n>{r['win_rate_pct']:.1f}%</td>
<td class=n>{r['cagr_pct']:+.2f}%</td>
<td class=n>{r['max_drawdown_pct']:+.2f}%</td>
<td class=n>{r['score_old']:.3f}</td>
<td class=n>{r['score_v2']:.3f}</td>
<td class=n style="color:#2563EB;font-weight:700">{r['score_v3']:.3f}</td>
</tr>"""
    return out

def html_trade_rows(df, limit=500):
    out=""
    if df.empty: return out
    for _,t in df.sort_values("entry_date",ascending=False).head(limit).iterrows():
        c=COLS.get(t["strategy"],"#666")
        pc2=pc(t["net_pnl_inr"]); res=t.get("result","")
        rbg="#DCFCE7" if res=="WIN" else "#FEE2E2"
        rc="#15803D"  if res=="WIN" else "#DC2626"
        tc=t.get("tax_category","")
        out+=f"""<tr>
<td><b style="color:{c}">{t['strategy']}</b></td>
<td style="font-family:monospace">{t['ticker']}</td>
<td>{t['entry_date']}</td><td>{t['exit_date']}</td>
<td class=n>{t['hold_days']}d</td>
<td class=n>&#8377;{t['entry_price']:,.2f}</td>
<td class=n>&#8377;{t['exit_price']:,.2f}</td>
<td class=n>{t['qty']}</td>
<td class=n>&#8377;{t['invested_inr']:,.0f}</td>
<td class=n style="color:{pc(t['gross_pnl_inr'])}">&#8377;{t['gross_pnl_inr']:,.0f}</td>
<td class=n style="color:#DC2626">&#8377;{t['total_costs_inr']:,.0f}</td>
<td class=n style="color:{pc2};font-weight:700">&#8377;{t['net_pnl_inr']:,.0f}</td>
<td class=n style="color:{pc2}">{t['pnl_pct']:+.2f}%</td>
<td class=n style="color:{pc2}">{t['net_pnl_pct']:+.2f}%</td>
<td><span style="background:{rbg};color:{rc};padding:2px 8px;border-radius:12px;font-size:11px;font-weight:700">{res}</span></td>
<td style="font-size:11px;color:#5A6478">{tc}</td>
</tr>"""
    return out

def build_html(sumdf, trades, eq, bm, skipped):
    sr=html_summary_rows(sumdf)
    rr,bmc=html_return_rows(sumdf,bm)
    tr2=html_trade_rows(trades)
    txr=html_tax_rows(sumdf)
    scr=html_score_rows(sumdf)
    tt=len(trades); tnp=trades["net_pnl_inr"].sum() if not trades.empty else 0
    tdep=trades["invested_inr"].sum() if not trades.empty else 0
    sk=len(skipped)
    bm_block=""
    if bm:
        bm_block=f"""<div class=bm>
<span class=bml>Benchmark: {bm.get('name','Nifty 50')}</span>
<span>Return: <b>{bm.get('return_pct',0):+.2f}%</b></span>
<span>CAGR: <b>{bm.get('cagr_pct',0):+.2f}%</b></span>
<span>Volatility: <b>{bm.get('vol_pct',0):.2f}%</b></span>
<span>Max DD: <b style="color:#DC2626">{bm.get('maxdd_pct',0):+.2f}%</b></span>
<span>Period: <b>{START} to {END}</b></span>
</div>"""
    leg="".join(f'<span class=leg><span class=dot style="background:{c}"></span><b>{s}</b></span>'
                for s,c in COLS.items())
    CSS="""
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
body{background:#F7F8FA;color:#14181F;font-family:'DM Sans',sans-serif;font-size:13px;line-height:1.55;padding:32px 40px}
h1{font-size:22px;font-weight:700;letter-spacing:-.4px;margin-bottom:4px}
h2{font-size:14px;font-weight:700;color:#14181F;margin:28px 0 12px;padding-left:12px;border-left:4px solid #2563EB}
.meta{color:#5A6478;font-size:12px;margin-bottom:22px}
.sec{background:#FFF;border:1px solid #E2E6ED;border-radius:12px;padding:24px;margin-bottom:18px;box-shadow:0 1px 4px rgba(0,0,0,.04)}
.rule-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:16px}
.rule{background:#F7F8FA;border:1px solid #E2E6ED;border-radius:8px;padding:14px}
.rn{font-weight:700;font-size:12px;margin-bottom:8px}
.rr2{font-size:11px;color:#5A6478;margin:3px 0}
.rr2 b{color:#14181F}
.mgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}
.mc{background:#F7F8FA;border:1px solid #E2E6ED;border-radius:10px;padding:14px 16px;border-top:3px solid #2563EB}
.ml{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#5A6478;margin-bottom:4px}
.mv{font-size:22px;font-weight:700}
.ms{font-size:11px;color:#5A6478;margin-top:2px}
table{width:100%;border-collapse:collapse;font-size:12px;margin-top:6px}
th{background:#F0F2F7;color:#5A6478;font-size:10px;text-transform:uppercase;letter-spacing:.5px;padding:8px 10px;border-bottom:2px solid #E2E6ED;text-align:left;white-space:nowrap}
td{padding:7px 10px;border-bottom:1px solid #F0F2F7;white-space:nowrap}
tr:hover td{background:#F8F9FF}
.n{text-align:right;font-family:'DM Mono',monospace}
.bm{background:#EFF6FF;border:1px solid #BFDBFE;border-radius:8px;padding:10px 16px;display:flex;gap:24px;align-items:center;margin-bottom:20px;font-size:12px}
.bml{font-weight:700;color:#1D4ED8}
.note{background:#FEF9C3;border:1px solid #FDE68A;border-radius:8px;padding:12px 16px;font-size:12px;color:#78350F;margin-top:12px}
.legends{display:flex;gap:18px;flex-wrap:wrap;margin-top:10px}
.leg{display:flex;align-items:center;gap:6px;font-size:12px}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block}
.skip{font-size:11px;color:#D97706;margin-top:8px}
"""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Nifty Quant — Professional Backtest {START} to {END}</title>
<style>{CSS}</style></head><body>

<h1>Nifty 500 Quant System — Professional Backtest Report</h1>
<div class="meta">Period: <b>{START} to {END}</b> ({PERIOD_YRS:.2f} yrs) &nbsp;&middot;&nbsp;
Reference Capital: <b>&#8377;{REF_CAP:,.0f}</b> (20 slots &times; &#8377;50,000) &nbsp;&middot;&nbsp;
Generated: <b>{TODAY}</b></div>

{bm_block}

<div class="sec">
<h2>Portfolio Overview</h2>
<div class="mgrid">
  <div class="mc" style="border-top-color:#2563EB"><div class="ml">Total Trades</div><div class="mv">{tt}</div></div>
  <div class="mc" style="border-top-color:{'#16A34A' if tnp>=0 else '#DC2626'}"><div class="ml">Net P&amp;L (All)</div><div class="mv" style="color:{'#16A34A' if tnp>=0 else '#DC2626'}">&#8377;{tnp:,.0f}</div></div>
  <div class="mc" style="border-top-color:#2563EB"><div class="ml">Total Deployed</div><div class="mv">&#8377;{tdep:,.0f}</div></div>
  <div class="mc" style="border-top-color:#D97706"><div class="ml">Skipped Signals</div><div class="mv" style="color:#D97706">{sk}</div><div class="ms">Slots full at signal time</div></div>
  <div class="mc" style="border-top-color:#2563EB"><div class="ml">Position Size</div><div class="mv">&#8377;50,000</div><div class="ms">Fixed per slot</div></div>
  <div class="mc" style="border-top-color:#2563EB"><div class="ml">Max Slots</div><div class="mv">20</div><div class="ms">Shared across strategies</div></div>
  <div class="mc" style="border-top-color:#5A6478"><div class="ml">Benchmark CAGR</div><div class="mv">{bmc:+.2f}%</div><div class="ms">Nifty 50 buy &amp; hold</div></div>
  <div class="mc" style="border-top-color:#2563EB"><div class="ml">Risk-Free Rate</div><div class="mv">7.0%</div><div class="ms">Used for Sharpe/Sortino</div></div>
</div>
<div class="legends">{leg}</div>
</div>

<div class="sec">
<h2>Strategy Rules</h2>
<div class="rule-grid">
<div class="rule"><div class="rn" style="color:{COLS['S1']}">S1 — Monthly EMA20 Breakout</div>
<div class="rr2"><b>Universe:</b> Nifty 100 (100 stocks)</div>
<div class="rr2"><b>Filter:</b> RSI14 &gt;60 Daily AND Weekly AND Monthly</div>
<div class="rr2"><b>Setup:</b> EMA10&gt;EMA20&gt;EMA50 monthly, close&gt;EMA50</div>
<div class="rr2"><b>Entry:</b> Price crosses above monthly EMA20</div>
<div class="rr2"><b>Exit:</b> EMA10 crosses below EMA20 + both slopes&lt;0</div></div>
<div class="rule"><div class="rn" style="color:{COLS['S2']}">S2 — Weekly EMA Pullback</div>
<div class="rr2"><b>Universe:</b> Nifty 100 (100 stocks)</div>
<div class="rr2"><b>Filter:</b> RSI14 &gt;60 Daily AND Weekly AND Monthly</div>
<div class="rr2"><b>Pre-cond:</b> Monthly EMA10&gt;EMA20&gt;EMA50</div>
<div class="rr2"><b>Entry:</b> Weekly EMA10 crosses above EMA20 after pullback</div>
<div class="rr2"><b>Exit:</b> Weekly EMA10 crosses below EMA20</div></div>
<div class="rule"><div class="rn" style="color:{COLS['S3']}">S3 — Monthly SSF50 [Opt-C]</div>
<div class="rr2"><b>Universe:</b> Default 50-stock sample</div>
<div class="rr2"><b>Setup:</b> Prev close &lt; SSF50 AND SSF200 AND SSF250</div>
<div class="rr2"><b>Entry:</b> Close&gt;SSF50 + RSI14&gt;RSI14_MA + MACD&gt;Signal + MACD&gt;0</div>
<div class="rr2"><b>Exit:</b> Monthly MACD bearish crossover</div></div>
<div class="rule"><div class="rn" style="color:{COLS['S4']}">S4 — Weekly SSF50 [Opt-D]</div>
<div class="rr2"><b>Universe:</b> Default 50-stock sample</div>
<div class="rr2"><b>Setup:</b> Prev close &lt; SSF50 only</div>
<div class="rr2"><b>Entry:</b> Close&gt;SSF50 + RSI14&gt;RSI14_MA + MACD&gt;Signal + both&gt;0</div>
<div class="rr2"><b>Exit:</b> Weekly MACD bearish crossover</div></div>
<div class="rule"><div class="rn" style="color:{COLS['S5']}">S5 — ETF SSF50 [Mod-1]</div>
<div class="rr2"><b>Universe:</b> 13 ETFs, no filter</div>
<div class="rr2"><b>Entry:</b> Close&gt;SSF50 + RSI14&gt;RSI14_MA (weekly)</div>
<div class="rr2"><b>Exit:</b> NO EXIT — held to today's price</div></div>
<div class="rr2"><b>Universe:</b> Default 50-stock sample</div>
<div class="rr2"><b>vs S4:</b> SSF50 crossover this bar NOT required</div>
<div class="rr2"><b>Entry:</b> Close&gt;SSF50 (already above OK) + RSI14 strictly&gt;RSI14_MA + MACD&gt;Signal + both&gt;0</div>
<div class="rr2"><b>Exit:</b> Weekly MACD bearish crossover (was above → now below)</div>
<div class="rr2"><b>SSF200/250:</b> Computed for reference, not used as gates</div></div>
</div></div>

<div class="sec"><h2>Trade Statistics</h2><div style="overflow-x:auto"><table>
<thead><tr><th>Strategy</th><th>Trades</th><th>Win Rate</th><th>W/L</th>
<th>Avg Win%</th><th>Avg Loss%</th><th>Expectancy%</th><th>Expectancy &#8377;</th>
<th>Profit Factor</th><th>R:R</th><th>Avg Hold</th><th>Med Hold</th>
<th>Max/Min Hold</th><th>Best Trade</th><th>Worst Trade</th></tr></thead>
<tbody>{sr}</tbody></table></div></div>

<div class="sec"><h2>Returns, Risk &amp; Risk-Adjusted Metrics</h2><div style="overflow-x:auto"><table>
<thead><tr><th>Strategy</th><th>Total Return</th><th>CAGR%</th>
<th>Net P&amp;L &#8377;</th><th>Gross P&amp;L &#8377;</th><th>Costs &#8377;</th>
<th>Deployed &#8377;</th><th>Net% on Dep.</th>
<th>Max DD%</th><th>Max DD &#8377;</th><th>Longest DD</th><th>Ann.Vol</th>
<th>Sharpe</th><th>Sortino</th><th>Calmar</th>
<th>VaR 95%</th><th>CVaR 95%</th>
<th>Alpha%</th><th>Beta</th><th>Info Ratio</th></tr></thead>
<tbody>{rr}</tbody></table></div>
<div class="note">Survivorship bias: backtest uses current universe — delisted stocks during 2023-2026 are excluded.
Reference Capital = &#8377;{REF_CAP:,.0f}. Risk-free rate = 7% p.a. Results are indicative only.</div></div>

<div class="sec"><h2>Tax Analysis (Indian Equity Delivery)</h2><div style="overflow-x:auto"><table>
<thead><tr><th>Strategy</th><th>Net P&amp;L &#8377;</th>
<th>STCG Tax &#8377; (20%)</th><th>LTCG Tax &#8377; (12.5%)</th>
<th>Total Tax &#8377;</th><th>Net After Tax &#8377;</th><th>Tax% of Profit</th></tr></thead>
<tbody>{txr}</tbody></table></div>
<div class="note">STCG: &lt;365 days @ 20%. LTCG: &ge;365 days @ 12.5% above &#8377;1.25L exemption. Consult a CA for actual liability.</div></div>

<div class="sec"><h2>Composite Ranking (Score V3 is primary)</h2><div style="overflow-x:auto"><table>
<thead><tr><th>Strategy</th><th>Expectancy%</th><th>Win Rate%</th><th>CAGR%</th><th>Max DD%</th>
<th>Score Old<br><small>Exp&times;WR/|DD|</small></th>
<th>Score V2<br><small>CAGR&times;WR/|DD|</small></th>
<th style="background:#EFF6FF;color:#2563EB">Score V3 &#9733;<br><small>Exp&times;WR&times;CAGR/|DD|&sup2;</small></th></tr></thead>
<tbody>{scr}</tbody></table></div></div>

<div class="sec">
<h2>Full Trade Log ({min(500,tt)} of {tt} trades, newest first)</h2>
<div style="overflow-x:auto"><table>
<thead><tr><th>Strategy</th><th>Ticker</th><th>Entry Date</th><th>Exit Date</th><th>Hold</th>
<th>Entry &#8377;</th><th>Exit &#8377;</th><th>Qty</th><th>Invested &#8377;</th>
<th>Gross P&amp;L &#8377;</th><th>Costs &#8377;</th>
<th>Net P&amp;L &#8377;</th><th>P&amp;L%</th><th>Net%</th>
<th>Result</th><th>Tax</th></tr></thead>
<tbody>{tr2}</tbody></table></div>
{"<div class='skip'>&#9888; "+str(sk)+" signal(s) skipped (all 20 slots full). See skipped_signals.csv</div>" if sk>0 else ""}
</div>

</body></html>"""

# ── Console print ─────────────────────────────────────────────────────────────
def print_results(sumdf, bm):
    W=118
    log.info(f"\n{'='*W}")
    log.info(f"  NIFTY QUANT — PROFESSIONAL BACKTEST  |  {START} to {END}  |  Capital INR {REF_CAP:,.0f}")
    log.info(f"{'='*W}")
    log.info(f"  {'Strategy':<10} {'Trades':>6} {'WR%':>6} {'CAGR%':>8} {'Net P&L INR':>14} "
             f"{'MaxDD%':>8} {'Sharpe':>7} {'Sortino':>8} {'Calmar':>7} "
             f"{'Alpha%':>7} {'Tax INR':>10} {'AfterTax INR':>14} {'V3*':>8}")
    log.info(f"  {'-'*W}")
    for _,r in sumdf.iterrows():
        if r.get("trades",0)==0: continue
        log.info(f"  {r['strategy']:<10} {r['trades']:>6} {r['win_rate_pct']:>5.1f}%"
                 f" {r['cagr_pct']:>+7.2f}% {r['net_pnl_inr']:>+14,.0f}"
                 f" {r['max_drawdown_pct']:>+7.2f}% {r['sharpe']:>7.2f}"
                 f" {r['sortino']:>8.2f} {r['calmar']:>7.2f}"
                 f" {r['alpha_pct']:>+6.2f}% {r['total_tax_inr']:>10,.0f}"
                 f" {r['net_after_tax_inr']:>+14,.0f} {r['score_v3']:>8.3f}")
    if bm:
        log.info(f"\n  Benchmark {bm.get('name','')}: "
                 f"Return={bm.get('return_pct',0):+.2f}%  "
                 f"CAGR={bm.get('cagr_pct',0):+.2f}%  "
                 f"Vol={bm.get('vol_pct',0):.2f}%  "
                 f"MaxDD={bm.get('maxdd_pct',0):+.2f}%")
    log.info(f"{'='*W}\n")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategies", nargs="+",
                        default=["S1","S2","S3","S4","S5"],
                        choices=["S1","S2","S3","S4","S5"])
    parser.add_argument("--universe", default=None)
    args = parser.parse_args()

    log.info(f"{'='*70}")
    log.info(f"  Nifty Quant — Professional Backtest")
    log.info(f"  Period     : {START} to {END}  ({PERIOD_YRS:.2f} yrs)")
    log.info(f"  Strategies : {' '.join(args.strategies)}")
    log.info(f"  Capital    : INR {POSITION_SIZE_INR:,}/slot  x  {MAX_POSITIONS} slots  =  INR {REF_CAP:,}")
    log.info(f"  Output     : {OUT.resolve()}")
    log.info(f"{'='*70}")

    stk = pd.read_csv(args.universe)["ticker"].tolist() if args.universe else DEFAULT50
    if not args.universe:
        log.info(f"  Using default {len(DEFAULT50)}-stock universe. Pass --universe nifty500.csv for full run.")

    pm = PM()
    if "S1" in args.strategies: run_s1(pm, NIFTY100, START, END)
    if "S2" in args.strategies: run_s2(pm, NIFTY100, START, END)
    if "S3" in args.strategies: run_s3(pm, stk,      START, END)
    if "S4" in args.strategies: run_s4(pm, stk,      START, END)
    if "S5" in args.strategies: run_s5(pm, ETFS,     START, END)

    # Force-close any still-open positions
    open_tks = {t["ticker"] for t in pm._open}
    pmap = {}
    for tk in open_tks:
        df2 = fetch(tk,"1wk",1)
        if df2 is None or df2.empty:
            df2 = fetch(tk,"1d",1)
        if df2 is not None and not df2.empty:
            pmap[tk] = float(df2["close"].iloc[-1])
    if pm._open:
        log.info(f"  Force-closing {len(pm._open)} open position(s) at latest price …")
        pm.force_close_all(TODAY, pmap)

    trades = pm.closed_df(); skipped = pm.skipped_df()
    log.info(f"\n  Total closed trades : {len(trades)}")
    log.info(f"  Skipped signals     : {len(skipped)}")

    log.info("  Fetching benchmark (Nifty 50) …")
    bm = get_benchmark()

    log.info("  Computing analytics …")
    rows = []
    for label in [s for s in ["S1","S2","S3","S4","S5"] if s in args.strategies]:
        sub = trades[trades["strategy"]==label] if not trades.empty else pd.DataFrame()
        eq  = equity_curve(sub, START, END)
        rows.append(analytics(label, sub, eq, bm))
        if not sub.empty:
            sub.to_csv(OUT/f"{label.lower()}_trades.csv", index=False)
        eq.to_csv(OUT/f"{label.lower()}_equity_curve.csv", index=False)

    eq_all = equity_curve(trades, START, END)
    rows.append(analytics("ALL", trades, eq_all, bm))
    sumdf = pd.DataFrame(rows)

    # Save all outputs
    trades.to_csv(OUT/"trade_log.csv", index=False)
    sumdf.to_csv(OUT/"summary.csv",    index=False)
    eq_all.to_csv(OUT/"equity_curve.csv", index=False)
    skipped.to_csv(OUT/"skipped_signals.csv", index=False)
    if not trades.empty and "tax_category" in trades.columns:
        tcols = [c for c in ["strategy","ticker","entry_date","exit_date","hold_days",
                              "gross_pnl_inr","tax_category","taxable_gain_inr",
                              "tax_inr","net_pnl_inr"] if c in trades.columns]
        trades[tcols].to_csv(OUT/"tax_report.csv", index=False)

    html = build_html(sumdf, trades, eq_all, bm, skipped)
    hp = OUT/"backtest_report.html"
    hp.write_text(html, encoding="utf-8")

    print_results(sumdf, bm)
    log.info(f"  Files saved to: {OUT.resolve()}/")
    log.info(f"  trade_log.csv  |  summary.csv  |  equity_curve.csv")
    log.info(f"  tax_report.csv  |  skipped_signals.csv")
    log.info(f"  s1_trades.csv ... s6_trades.csv")
    log.info(f"  backtest_report.html  <-- open in browser")
    log.info("")

if __name__ == "__main__":
    main()
