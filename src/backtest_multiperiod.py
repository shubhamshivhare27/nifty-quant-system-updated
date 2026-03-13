#!/usr/bin/env python3
"""
backtest_multiperiod.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Runs backtest_professional.py logic across 3 historical periods + full
period, then produces a single HTML comparison report.

Periods tested:
  P1 : 2010-01-01  →  2014-12-31   (4 yrs — sideways / recovery post-GFC)
  P2 : 2014-01-01  →  2018-12-31   (4 yrs — bull + demonetization)
  P3 : 2018-01-01  →  2022-12-31   (4 yrs — bear + COVID + recovery)
  P4 : 2023-01-01  →  2026-03-07   (full backtest, same as backtest_professional)

Usage:
  python backtest_multiperiod.py
  python backtest_multiperiod.py --strategies S1 S2 S3 S4 S5
  python backtest_multiperiod.py --universe nifty500.csv

Output → backtest_results_multiperiod/
  summary_all_periods.csv          — all strategies × all periods
  backtest_multiperiod_report.html — visual comparison report
  P1_trade_log.csv  ...  P4_trade_log.csv
  P1_summary.csv    ...  P4_summary.csv
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import argparse, logging, math, warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# ── Periods ───────────────────────────────────────────────────────────────────
PERIODS = [
    ("P1", "2010-01-01", "2014-12-31", "2010–2014  (Sideways / Post-GFC Recovery)"),
    ("P2", "2014-01-01", "2018-12-31", "2014–2018  (Bull Run + Demonetization)"),
    ("P3", "2018-01-01", "2022-12-31", "2018–2022  (Bear + COVID + Recovery)"),
    ("P4", "2023-01-01", "2026-03-07", "2023–2026  (Current Period)"),
]
PERIOD_COLORS = {
    "P1": "#3B82F6", "P2": "#10B981", "P3": "#F59E0B", "P4": "#8B5CF6"
}

# ── Constants (same as backtest_professional) ─────────────────────────────────
POSITION_SIZE_INR = 50_000
MAX_POSITIONS     = 20
REF_CAP           = POSITION_SIZE_INR * MAX_POSITIONS
RISK_FREE         = 0.07
STCG_RATE         = 0.20
LTCG_RATE         = 0.125
LTCG_EXEMPT       = 125_000
BM_TICKER         = "^NSEI"
WARMUP_WEEKLY     = 100
WARMUP_MONTHLY    = 60
SSF_BUFFER        = 0.003

OUT = Path("backtest_results_multiperiod")
OUT.mkdir(exist_ok=True)

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

# ── Data fetch (shared cache across all period runs) ──────────────────────────
_cache = {}

def _fetch(ticker, interval, years=16):
    key = (ticker, interval)
    if key in _cache:
        return _cache[key]
    try:
        end   = datetime.today()
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

def fetch(t, iv, yrs=16): return _fetch(t, iv, yrs)
def fetchm(t, ivs=("1d","1wk","1mo"), yrs=16): return {iv: _fetch(t,iv,yrs) for iv in ivs}

def align(tgt_dates, src_df, src_series):
    sd = src_df["date"].values; sv2 = src_series.values
    out = np.full(len(tgt_dates), np.nan)
    for i, td in enumerate(tgt_dates):
        m = sd <= td
        if m.any(): out[i] = sv2[m][-1]
    return pd.Series(out, dtype=float)

# ── Indicators (identical to backtest_professional) ───────────────────────────
def ema(s, n):
    s = s.reset_index(drop=True).astype(float)
    out = pd.Series(np.nan, index=s.index)
    seed = s.iloc[:n].mean()
    if np.isnan(seed): return out
    out.iloc[n-1] = seed
    k = 2/(n+1)
    for i in range(n, len(s)):
        if np.isnan(s.iloc[i]): out.iloc[i] = out.iloc[i-1]
        else: out.iloc[i] = s.iloc[i]*k + out.iloc[i-1]*(1-k)
    return out

def ssf(s, n):
    s = s.astype(float).reset_index(drop=True)
    out = pd.Series(np.nan, index=s.index)
    a = math.exp(-math.sqrt(2)*math.pi/n)
    b = 2*a*math.cos(math.radians(math.sqrt(2)*180/n))
    c2=b; c3=-a*a; c1=1-c2-c3
    for i in range(len(s)):
        p0 = s.iloc[i]   if not np.isnan(s.iloc[i])   else 0.0
        p1 = s.iloc[i-1] if i>=1 and not np.isnan(s.iloc[i-1]) else p0
        s1 = out.iloc[i-1] if i>=1 and not np.isnan(out.iloc[i-1]) else p0
        s2 = out.iloc[i-2] if i>=2 and not np.isnan(out.iloc[i-2]) else p0
        out.iloc[i] = c1*(p0+p1)/2 + c2*s1 + c3*s2
    return out

def rsi(s, n=14):
    s = s.reset_index(drop=True).astype(float)
    d = s.diff()
    g = d.clip(lower=0); l = (-d).clip(lower=0)
    ag = g.ewm(com=n-1, min_periods=n).mean()
    al = l.ewm(com=n-1, min_periods=n).mean()
    rs = ag / al.replace(0, np.nan)
    return (100 - 100/(1+rs)).where(al != 0, 100)

def rsima(ri, n=14): return ri.rolling(n, min_periods=n).mean()

def slope(s, n=3):
    s = s.reset_index(drop=True).astype(float)
    out = pd.Series(np.nan, index=s.index)
    for i in range(n-1, len(s)):
        w = s.iloc[i-n+1:i+1].dropna()
        if len(w) == n: out.iloc[i] = (w.iloc[-1] - w.iloc[0]) / (n-1)
    return out

def macd(s, f=12, sl=26, sg=9):
    ml = ema(s,f) - ema(s,sl)
    return ml, ema(ml.ffill(), sg)

def sv(s, i):
    try:
        v = s.iloc[i]
        return None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v)
    except: return None

# ── Position Manager (same logic as backtest_professional) ────────────────────
class PM:
    def __init__(self):
        self._open   = []
        self._closed = []
        self._skipped= []
        self._trade_n= 0

    def open(self, strategy, ticker, date, price):
        if len(self._open) >= MAX_POSITIONS:
            self._skipped.append({"strategy":strategy,"ticker":ticker,
                                  "date":str(date)[:10],"price":price})
            return None
        self._trade_n += 1
        qty   = max(1, int(POSITION_SIZE_INR // price))
        inv   = round(qty * price, 2)
        tid   = f"{strategy}_{ticker}_{str(date)[:10]}"
        entry = {"trade_id":tid,"strategy":strategy,"ticker":ticker,
                 "entry_date":str(date)[:10],"entry_price":round(price,2),
                 "qty":qty,"invested_inr":inv,"slot_no":self._trade_n}
        self._open.append(entry)
        return entry

    def close(self, ticker, strategy, date, price):
        for t in list(self._open):
            if t["ticker"]==ticker and t["strategy"]==strategy:
                self._open.remove(t)
                ep   = round(price,2)
                days = (pd.Timestamp(str(date)[:10]) -
                        pd.Timestamp(t["entry_date"])).days
                gross= round((ep - t["entry_price"]) * t["qty"], 2)
                pct  = round(gross / t["invested_inr"] * 100, 4)
                # Costs
                brk  = 40.0
                stt  = round(ep * t["qty"] * 0.001, 2)
                exc  = round((t["invested_inr"] + ep*t["qty"]) * 0.0000345, 2)
                sebi = round((t["invested_inr"] + ep*t["qty"]) * 0.000001, 2)
                gst  = round((brk + exc + sebi) * 0.18, 2)
                stmp = round(t["invested_inr"] * 0.00015, 2)
                cost = round(brk+stt+exc+sebi+gst+stmp, 2)
                net  = round(gross - cost, 2)
                npct = round(net / t["invested_inr"] * 100, 4)
                # Tax
                ltcg_flag = days >= 365
                cat  = "LTCG" if ltcg_flag else ("STCG" if net > 0 else "NIL")
                tax  = 0.0
                if net > 0:
                    if ltcg_flag:
                        taxable = max(0, net - LTCG_EXEMPT/MAX_POSITIONS)
                        tax = round(taxable * LTCG_RATE, 2)
                    else:
                        tax = round(net * STCG_RATE, 2)
                t.update({"status":"CLOSED","exit_date":str(date)[:10],
                          "exit_price":ep,"hold_days":days,
                          "gross_pnl_inr":gross,"pnl_pct":pct,
                          "net_pnl_inr":net,"net_pnl_pct":npct,
                          "result":"WIN" if net>0 else "LOSS",
                          "brokerage":brk,"stt":stt,"exchange_charges":exc,
                          "sebi_charges":sebi,"gst":gst,"stamp_duty":stmp,
                          "total_costs_inr":cost,"tax_category":cat,
                          "taxable_gain_inr":round(max(0,net),2),
                          "tax_inr":tax})
                self._closed.append(t)
                return t
        return None

    def force_close_all(self, date, price_map):
        for t in list(self._open):
            px = price_map.get(t["ticker"], t["entry_price"])
            self.close(t["ticker"], t["strategy"], date, px)

    def closed_df(self):
        return pd.DataFrame(self._closed) if self._closed else pd.DataFrame()

    def skipped_df(self):
        return pd.DataFrame(self._skipped) if self._skipped else pd.DataFrame()

# ── Strategy runners (S1–S5, same logic as backtest_professional) ─────────────
def run_s1(pm, tickers, s, e):
    log.info(f"  S1  Monthly EMA20 Breakout  | {len(tickers)} stocks")
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
                if i < WARMUP_MONTHLY: continue
                bd=dt.iloc[i]; cn,cp=sv(cl,i),sv(cl,i-1)
                e10n,e10p=sv(e10,i),sv(e10,i-1)
                e20n,e20p=sv(e20,i),sv(e20,i-1)
                e50n=sv(e50,i); s10=sv(sl10,i); s20=sv(sl20,i)
                rdi=sv(rda,i); rwi=sv(rwa,i); rmi=sv(rm,i)
                if None in (cn,cp,e10n,e10p,e20n,e20p,e50n,rdi,rwi,rmi): continue
                if not inp:
                    if not (rdi>60 and rwi>60 and rmi>60): continue
                    if (e10n>e20n>e50n) and (cn>e50n) and (cp<e20p) and (cn>e20n):
                        if st<=bd<=et:
                            inp=True; pm.open("S1",tk,bd,cn)
                else:
                    if ((e10p>e20p) and (e10n<e20n) and (s10 or 0)<0 and (s20 or 0)<0) or bd>et:
                        pm.close(tk,"S1",bd,cn); inp=False
            if inp: pm.close(tk,"S1",dt.iloc[-1],sv(cl,len(cl)-1))
        except Exception as exc: log.debug(f"S1 {tk}: {exc}")

def run_s2(pm, tickers, s, e):
    log.info(f"  S2  Weekly EMA Pullback     | {len(tickers)} stocks")
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
                if i < WARMUP_WEEKLY: continue
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
                        inp=True; pm.open("S2",tk,bd,cn)
                else:
                    if ((e10p>e20p) and (e10n<e20n)) or bd>et:
                        pm.close(tk,"S2",bd,cn); inp=False
            if inp: pm.close(tk,"S2",dtw.iloc[-1],sv(clw,len(clw)-1))
        except Exception as exc: log.debug(f"S2 {tk}: {exc}")

def run_s3(pm, tickers, s, e):
    log.info(f"  S3  Monthly SSF50 [Opt-C]   | {len(tickers)} stocks")
    st = pd.Timestamp(s); et = pd.Timestamp(e)
    for tk in tickers:
        dm = fetch(tk,"1mo",16)
        if dm is None or len(dm)<60: continue
        try:
            cl=dm["close"]; dt=dm["date"]
            sf50=ssf(cl,50); sf200=ssf(cl,200); sf250=ssf(cl,250)
            ri=rsi(cl,14); rim=rsima(ri,14); ml,ms=macd(cl)
            inp=False
            for i in range(2,len(cl)):
                if i < WARMUP_MONTHLY: continue
                bd=dt.iloc[i]; cn,cp=sv(cl,i),sv(cl,i-1)
                s50n,s50p=sv(sf50,i),sv(sf50,i-1)
                s200p=sv(sf200,i-1); s250p=sv(sf250,i-1)
                r,rm=sv(ri,i),sv(rim,i)
                mln,mlp=sv(ml,i),sv(ml,i-1); msn,msp=sv(ms,i),sv(ms,i-1)
                if None in (cn,cp,s50n,s50p,s200p,s250p,r,rm,mln,mlp,msn,msp): continue
                if not inp:
                    if (cp<s50p) and (cp<s200p) and (cp<s250p):
                        if (cn > s50n*(1+SSF_BUFFER)) and (r>rm) and (mln>msn) and (mln>0):
                            if st<=bd<=et:
                                inp=True; pm.open("S3",tk,bd,cn)
                else:
                    if ((mlp>msp) and (mln<msn)) or bd>et:
                        pm.close(tk,"S3",bd,cn); inp=False
            if inp: pm.close(tk,"S3",dt.iloc[-1],sv(cl,len(cl)-1))
        except Exception as exc: log.debug(f"S3 {tk}: {exc}")

def run_s4(pm, tickers, s, e):
    log.info(f"  S4  Weekly SSF50 [Opt-D]    | {len(tickers)} stocks")
    st = pd.Timestamp(s); et = pd.Timestamp(e)
    for tk in tickers:
        dw = fetch(tk,"1wk",16)
        if dw is None or len(dw)<60: continue
        try:
            cl=dw["close"]; dt=dw["date"]
            sf50=ssf(cl,50); ri=rsi(cl,14); rim=rsima(ri,14); ml,ms=macd(cl)
            inp=False; below_ssf=True
            for i in range(2,len(cl)):
                if i < WARMUP_WEEKLY: continue
                bd=dt.iloc[i]; cn,cp=sv(cl,i),sv(cl,i-1)
                s50n,s50p=sv(sf50,i),sv(sf50,i-1)
                r,rm=sv(ri,i),sv(rim,i)
                mln,mlp=sv(ml,i),sv(ml,i-1); msn,msp=sv(ms,i),sv(ms,i-1)
                if None in (cn,cp,s50n,s50p,r,rm,mln,mlp,msn,msp): continue
                if not inp and cn < s50n: below_ssf=True
                if not inp:
                    if below_ssf and (cp<s50p) and (cn > s50n*(1+SSF_BUFFER)) and (r>rm) and (mln>msn) and (mln>0) and (msn>0):
                        if st<=bd<=et:
                            inp=True; below_ssf=False; pm.open("S4",tk,bd,cn)
                else:
                    if ((mlp>msp) and (mln<msn)) or bd>et:
                        pm.close(tk,"S4",bd,cn); inp=False
            if inp: pm.close(tk,"S4",dt.iloc[-1],sv(cl,len(cl)-1))
        except Exception as exc: log.debug(f"S4 {tk}: {exc}")

def run_s5(pm, tickers, s, e):
    log.info(f"  S5  ETF SSF50 [Mod-1]       | {len(tickers)} ETFs")
    st = pd.Timestamp(s); et = pd.Timestamp(e)
    # For historical periods, S5 exits at period end (not held to today)
    for tk in tickers:
        dw = fetch(tk,"1wk",16)
        if dw is None or len(dw)<60: continue
        try:
            cl=dw["close"]; dt=dw["date"]
            sf50=ssf(cl,50); ri=rsi(cl,14); rim=rsima(ri,14)
            # Get period-end price for closing open S5 trades
            period_mask = dt <= pd.Timestamp(e)
            if not period_mask.any(): continue
            last_i = period_mask.values.nonzero()[0][-1]
            todpx = sv(cl, last_i)
            toddt = str(dt.iloc[last_i])[:10]
            if todpx is None: continue
            inp=False
            for i in range(2,len(cl)):
                if i < WARMUP_WEEKLY: continue
                bd=dt.iloc[i]; cn,cp=sv(cl,i),sv(cl,i-1)
                s50n,s50p=sv(sf50,i),sv(sf50,i-1)
                r,rm=sv(ri,i),sv(rim,i)
                if None in (cn,cp,s50n,s50p,r,rm): continue
                if inp and cn<s50n: inp=False
                if (not inp) and (cp<s50p) and (cn > s50n*(1+SSF_BUFFER)) and (r>rm):
                    if st<=bd<=et:
                        inp=True
                        if pm.open("S5",tk,bd,cn):
                            pm.close(tk,"S5",toddt,todpx)
        except Exception as exc: log.debug(f"S5 {tk}: {exc}")

# ── Analytics (same as backtest_professional) ─────────────────────────────────
def equity_curve(trades, s, e):
    dr = pd.date_range(start=s, end=e, freq="D")
    daily = pd.Series(0.0, index=dr)
    if not trades.empty:
        for d_str,v in trades.groupby("exit_date")["net_pnl_inr"].sum().items():
            try:
                d = pd.Timestamp(d_str)
                if d in daily.index: daily[d] += v
            except: pass
    eq = REF_CAP + daily.cumsum()
    dd = (eq - eq.cummax()) / eq.cummax() * 100
    return pd.DataFrame({"date":dr,"equity":eq.values,"drawdown":dd.values})

def analytics(label, trades, eq, bm_ret, period_yrs):
    res = {"strategy": label, "total_trades": 0, "win_trades": 0,
           "loss_trades": 0, "win_rate_pct": 0, "avg_hold_days": 0,
           "gross_pnl_inr": 0, "total_costs_inr": 0, "total_tax_inr": 0,
           "net_pnl_inr": 0, "cagr_pct": 0, "total_return_pct": 0,
           "sharpe": 0, "sortino": 0, "calmar": 0,
           "maxdd_pct": 0, "avg_win_inr": 0, "avg_loss_inr": 0,
           "expectancy_pct": 0, "score_v3": 0}
    if trades.empty: return res
    wins = trades[trades["result"]=="WIN"]
    loss = trades[trades["result"]=="LOSS"]
    n = len(trades); w = len(wins); l = len(loss)
    wr = round(w/n*100, 2) if n else 0
    avg_w = wins["net_pnl_inr"].mean() if len(wins) else 0
    avg_l = loss["net_pnl_inr"].mean() if len(loss) else 0
    exp_inr = wr/100*avg_w + (1-wr/100)*avg_l
    exp_pct = round(exp_inr/POSITION_SIZE_INR*100, 4) if POSITION_SIZE_INR else 0
    net_pnl = trades["net_pnl_inr"].sum()
    ret_pct = round(net_pnl/REF_CAP*100, 2)
    cagr = round(((REF_CAP+net_pnl)/REF_CAP)**(1/max(period_yrs,0.1))*100-100, 2)
    dr = eq["equity"].pct_change().dropna()
    sharpe = round((dr.mean()*252 - RISK_FREE/100) / (dr.std()*math.sqrt(252)+1e-9), 2)
    neg = dr[dr<0]
    sortino = round((dr.mean()*252 - RISK_FREE/100) / (neg.std()*math.sqrt(252)+1e-9), 2)
    mdd = round(eq["drawdown"].min(), 2)
    calmar = round(cagr / abs(mdd+1e-9), 2)
    score = round((exp_pct * wr * cagr) / (mdd**2 + 1e-9), 4)
    res.update({
        "total_trades": n, "win_trades": w, "loss_trades": l,
        "win_rate_pct": wr, "avg_hold_days": round(trades["hold_days"].mean(),1),
        "gross_pnl_inr": round(trades["gross_pnl_inr"].sum(),2),
        "total_costs_inr": round(trades["total_costs_inr"].sum(),2),
        "total_tax_inr": round(trades["tax_inr"].sum(),2) if "tax_inr" in trades.columns else 0,
        "net_pnl_inr": round(net_pnl,2),
        "total_return_pct": ret_pct, "cagr_pct": cagr,
        "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
        "maxdd_pct": mdd,
        "avg_win_inr": round(avg_w,2), "avg_loss_inr": round(avg_l,2),
        "expectancy_pct": exp_pct, "score_v3": score,
        "benchmark_cagr": round(bm_ret,2),
        "alpha": round(cagr - bm_ret, 2),
    })
    return res

def get_benchmark_cagr(s, e):
    try:
        df = fetch(BM_TICKER,"1d",16)
        if df is None or df.empty: return 0.0
        df = df[(df["date"]>=pd.Timestamp(s)) & (df["date"]<=pd.Timestamp(e))]
        if len(df)<10: return 0.0
        sp=df["close"].iloc[0]; ep=df["close"].iloc[-1]
        yrs=(df["date"].iloc[-1]-df["date"].iloc[0]).days/365.25
        return ((ep/sp)**(1/yrs)-1)*100 if yrs>0 else 0.0
    except: return 0.0

# ── HTML report ───────────────────────────────────────────────────────────────
SCOLS = {"S1":"#3B82F6","S2":"#10B981","S3":"#F59E0B","S4":"#EF4444","S5":"#8B5CF6","ALL":"#94A3B8"}

def fmt(v, suffix="", prefix=""):
    if v is None or (isinstance(v,float) and math.isnan(v)): return "—"
    if isinstance(v,float): return f"{prefix}{v:,.2f}{suffix}"
    return f"{prefix}{v}{suffix}"

def color_val(v, good_positive=True):
    try:
        f = float(v)
        if f > 0: return "#16A34A" if good_positive else "#DC2626"
        if f < 0: return "#DC2626" if good_positive else "#16A34A"
    except: pass
    return "#14181F"

def build_html(all_rows, period_trades):
    strategies = ["S1","S2","S3","S4","S5","ALL"]
    period_ids  = [p[0] for p in PERIODS]
    period_labels = {p[0]: p[3] for p in PERIODS}

    # Period summary cards per strategy
    def strategy_period_table(strat):
        metrics = [
            ("CAGR %",        "cagr_pct",         True,  "%"),
            ("Total Return %", "total_return_pct", True,  "%"),
            ("Win Rate %",     "win_rate_pct",     True,  "%"),
            ("Max DD %",       "maxdd_pct",        False, "%"),
            ("Sharpe",         "sharpe",           True,  ""),
            ("Trades",         "total_trades",     None,  ""),
            ("Net P&L ₹",      "net_pnl_inr",      True,  ""),
            ("Expectancy %",   "expectancy_pct",   True,  "%"),
            ("Alpha %",        "alpha",            True,  "%"),
            ("Score V3",       "score_v3",         True,  ""),
        ]
        rows_html = ""
        for label, key, good_pos, suffix in metrics:
            row = f'<tr><td class="ml">{label}</td>'
            for pid in period_ids:
                r = next((x for x in all_rows if x["strategy"]==strat and x.get("period")==pid), {})
                v = r.get(key, "—")
                try:
                    fv = float(v)
                    disp = f"{fv:,.2f}{suffix}" if suffix else f"{fv:,.2f}"
                    if key == "total_trades": disp = str(int(fv))
                    col = color_val(fv, good_pos) if good_pos is not None else "#14181F"
                except:
                    disp = "—"; col = "#14181F"
                row += f'<td style="color:{col};font-weight:600">{disp}</td>'
            rows_html += row + "</tr>"
        return rows_html

    strategy_sections = ""
    for s in ["S1","S2","S3","S4","S5"]:
        sname = {
            "S1":"S1 — Monthly EMA20 Breakout",
            "S2":"S2 — Weekly EMA Pullback",
            "S3":"S3 — Monthly SSF50 [Opt-C]",
            "S4":"S4 — Weekly SSF50 [Opt-D]",
            "S5":"S5 — ETF SSF50 [Mod-1]",
        }[s]
        period_headers = "".join(f'<th style="color:{PERIOD_COLORS[p]}">{period_labels[p].split("(")[0].strip()}</th>' for p in period_ids)
        table_rows = strategy_period_table(s)
        strategy_sections += f"""
<div class="sec">
  <h2 style="border-color:{SCOLS[s]}">{sname}</h2>
  <div style="overflow-x:auto">
  <table class="ptable">
    <thead><tr><th>Metric</th>{period_headers}</tr></thead>
    <tbody>{table_rows}</tbody>
  </table>
  </div>
</div>"""

    # Cross-strategy comparison per period
    period_sections = ""
    for pid, pstart, pend, plabel in PERIODS:
        rows = [r for r in all_rows if r.get("period")==pid and r["strategy"] != "ALL"]
        if not rows: continue
        strat_headers = "".join(f'<th style="color:{SCOLS[r["strategy"]]}">{r["strategy"]}</th>' for r in rows)
        metrics2 = [("CAGR %","cagr_pct",True,"%"),
                    ("Win Rate %","win_rate_pct",True,"%"),
                    ("Max DD %","maxdd_pct",False,"%"),
                    ("Sharpe","sharpe",True,""),
                    ("Net P&L ₹","net_pnl_inr",True,""),
                    ("Trades","total_trades",None,""),
                    ("Alpha %","alpha",True,"%"),
                    ("Score V3","score_v3",True,"")]
        trows = ""
        for label, key, gp, suffix in metrics2:
            trows += f'<tr><td class="ml">{label}</td>'
            for r in rows:
                v = r.get(key,"—")
                try:
                    fv = float(v)
                    disp = f"{fv:,.2f}{suffix}" if suffix else f"{fv:,.2f}"
                    if key=="total_trades": disp=str(int(fv))
                    col = color_val(fv, gp) if gp is not None else "#14181F"
                except:
                    disp="—"; col="#14181F"
                trows += f'<td style="color:{col};font-weight:600">{disp}</td>'
            trows += "</tr>"
        period_sections += f"""
<div class="sec">
  <h2 style="border-color:{PERIOD_COLORS[pid]}">{plabel}</h2>
  <div style="overflow-x:auto">
  <table class="ptable">
    <thead><tr><th>Metric</th>{strat_headers}</tr></thead>
    <tbody>{trows}</tbody>
  </table>
  </div>
</div>"""

    now = datetime.now().strftime("%d %b %Y %H:%M")
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Nifty Quant — Multi-Period Backtest</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap');
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#F7F8FA;color:#14181F;font-family:'DM Sans',sans-serif;font-size:13px;line-height:1.55;padding:32px 40px}}
h1{{font-size:22px;font-weight:700;letter-spacing:-.4px;margin-bottom:4px}}
h2{{font-size:14px;font-weight:700;color:#14181F;margin:0 0 14px;padding-left:12px;border-left:4px solid #2563EB}}
.meta{{color:#5A6478;font-size:12px;margin-bottom:28px}}
.sec{{background:#FFF;border:1px solid #E2E6ED;border-radius:12px;padding:24px;margin-bottom:18px;box-shadow:0 1px 4px rgba(0,0,0,.04)}}
.tab-bar{{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}}
.tab{{padding:7px 18px;border-radius:20px;cursor:pointer;font-size:12px;font-weight:600;border:1px solid #E2E6ED;background:#fff;color:#5A6478}}
.tab.active{{background:#14181F;color:#fff;border-color:#14181F}}
.panel{{display:none}}.panel.active{{display:block}}
.ptable{{width:100%;border-collapse:collapse;font-size:12px}}
.ptable th{{background:#F7F8FA;padding:8px 12px;text-align:right;font-size:11px;font-weight:700;color:#5A6478;border-bottom:2px solid #E2E6ED;white-space:nowrap}}
.ptable th:first-child{{text-align:left}}
.ptable td{{padding:7px 12px;text-align:right;border-bottom:1px solid #F0F2F5}}
.ptable td.ml{{text-align:left;color:#5A6478;font-weight:500}}
.ptable tr:hover td{{background:#F7F8FA}}
.pgrid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:20px}}
.pc{{background:#F7F8FA;border:1px solid #E2E6ED;border-radius:8px;padding:12px 14px;border-top:3px solid #2563EB}}
.pl{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#5A6478;margin-bottom:4px}}
.pv{{font-size:16px;font-weight:700}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;margin-left:6px}}
</style>
<script>
function showTab(id){{
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.getElementById('tab-'+id).classList.add('active');
  document.getElementById('panel-'+id).classList.add('active');
}}
</script>
</head><body>
<h1>Nifty Quant — Multi-Period Backtest Report</h1>
<p class="meta">Generated: {now} &nbsp;|&nbsp; Capital: ₹{REF_CAP:,} (₹{POSITION_SIZE_INR:,} × {MAX_POSITIONS} slots) &nbsp;|&nbsp; Strategies: S1 S2 S3 S4 S5</p>

<div class="pgrid">
{''.join(f'<div class="pc" style="border-top-color:{PERIOD_COLORS[p[0]]}"><div class="pl">{p[0]}</div><div class="pv">{p[3].split("(")[0].strip()}</div></div>' for p in PERIODS)}
</div>

<div class="tab-bar">
  <button class="tab active" id="tab-bystrat" onclick="showTab('bystrat')">By Strategy</button>
  <button class="tab" id="tab-byperiod" onclick="showTab('byperiod')">By Period</button>
</div>

<div class="panel active" id="panel-bystrat">
<p style="color:#5A6478;font-size:12px;margin-bottom:16px">Each strategy shown across all 4 periods — compare consistency over time.</p>
{strategy_sections}
</div>

<div class="panel" id="panel-byperiod">
<p style="color:#5A6478;font-size:12px;margin-bottom:16px">Each period shown across all strategies — see which strategy dominated each regime.</p>
{period_sections}
</div>

</body></html>"""
    return html

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategies", nargs="+",
                        default=["S1","S2","S3","S4","S5"],
                        choices=["S1","S2","S3","S4","S5"])
    parser.add_argument("--universe", default=None)
    args = parser.parse_args()

    stk = pd.read_csv(args.universe)["ticker"].tolist() if args.universe else DEFAULT50
    if not args.universe:
        log.info(f"Using default {len(DEFAULT50)}-stock universe")

    log.info("="*68)
    log.info("  Nifty Quant — Multi-Period Backtest")
    log.info(f"  Strategies : {' '.join(args.strategies)}")
    log.info(f"  Capital    : INR {POSITION_SIZE_INR:,}/slot × {MAX_POSITIONS} = INR {REF_CAP:,}")
    log.info(f"  Periods    : {len(PERIODS)}  ({' | '.join(p[0] for p in PERIODS)})")
    log.info("="*68)

    all_rows = []
    period_trades = {}

    for pid, pstart, pend, plabel in PERIODS:
        period_yrs = (pd.Timestamp(pend) - pd.Timestamp(pstart)).days / 365.25
        log.info(f"\n{'─'*68}")
        log.info(f"  Period {pid}: {plabel}")
        log.info(f"{'─'*68}")

        pm = PM()
        if "S1" in args.strategies: run_s1(pm, NIFTY100, pstart, pend)
        if "S2" in args.strategies: run_s2(pm, NIFTY100, pstart, pend)
        if "S3" in args.strategies: run_s3(pm, stk,      pstart, pend)
        if "S4" in args.strategies: run_s4(pm, stk,      pstart, pend)
        if "S5" in args.strategies: run_s5(pm, ETFS,     pstart, pend)

        # Force-close open positions at period end
        open_tks = {t["ticker"] for t in pm._open}
        pmap = {}
        for tk in open_tks:
            df2 = fetch(tk,"1wk",16)
            if df2 is None or df2.empty:
                df2 = fetch(tk,"1d",16)
            if df2 is not None and not df2.empty:
                mask = df2["date"] <= pd.Timestamp(pend)
                if mask.any():
                    pmap[tk] = float(df2[df2["date"]<=pd.Timestamp(pend)]["close"].iloc[-1])
        if pm._open:
            log.info(f"  Force-closing {len(pm._open)} open position(s) at period end …")
            pm.force_close_all(pend, pmap)

        trades = pm.closed_df()
        bm_cagr = get_benchmark_cagr(pstart, pend)
        log.info(f"  Closed trades: {len(trades)} | Benchmark CAGR: {bm_cagr:.2f}%")

        period_trades[pid] = trades

        # Save period files
        if not trades.empty:
            trades.to_csv(OUT/f"{pid}_trade_log.csv", index=False)

        rows = []
        for label in [s for s in ["S1","S2","S3","S4","S5"] if s in args.strategies]:
            sub = trades[trades["strategy"]==label] if not trades.empty else pd.DataFrame()
            eq  = equity_curve(sub, pstart, pend)
            row = analytics(label, sub, eq, bm_cagr, period_yrs)
            row["period"] = pid
            row["period_label"] = plabel
            rows.append(row)

        eq_all = equity_curve(trades, pstart, pend)
        row_all = analytics("ALL", trades, eq_all, bm_cagr, period_yrs)
        row_all["period"] = pid; row_all["period_label"] = plabel
        rows.append(row_all)

        pd.DataFrame(rows).to_csv(OUT/f"{pid}_summary.csv", index=False)

        # Print period summary
        W = 68
        log.info(f"\n  {'Strategy':<12} {'Trades':>7} {'WinRate':>8} {'CAGR%':>8} {'MaxDD%':>8} {'Sharpe':>7} {'Alpha%':>7}")
        log.info(f"  {'-'*60}")
        for r in rows:
            log.info(f"  {r['strategy']:<12} {r['total_trades']:>7} {r['win_rate_pct']:>7.1f}%"
                     f" {r['cagr_pct']:>7.2f}% {r['maxdd_pct']:>7.2f}% {r['sharpe']:>7.2f}"
                     f" {r.get('alpha',0):>6.2f}%")

        all_rows.extend(rows)

    # Master summary CSV
    master = pd.DataFrame(all_rows)
    master.to_csv(OUT/"summary_all_periods.csv", index=False)

    # HTML report
    html = build_html(all_rows, period_trades)
    hp = OUT/"backtest_multiperiod_report.html"
    hp.write_text(html, encoding="utf-8")

    log.info(f"\n{'='*68}")
    log.info(f"  DONE — outputs in: {OUT.resolve()}/")
    log.info(f"  summary_all_periods.csv")
    log.info(f"  P1_summary.csv  P2_summary.csv  P3_summary.csv  P4_summary.csv")
    log.info(f"  P1_trade_log.csv ... P4_trade_log.csv")
    log.info(f"  backtest_multiperiod_report.html  ← open in browser")
    log.info(f"{'='*68}")

if __name__ == "__main__":
    main()
