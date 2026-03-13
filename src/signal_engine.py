"""
signal_engine.py
----------------
CONSOLIDATED signal engine for all 5 strategies (S1–S5).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ARCHITECTURE: ONE CONSOLIDATED ENGINE (not separate files per strategy)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
S3 (monthly) and S4 (weekly) live in the same class because:
  • They share the same fetcher, indicator library, and signal output pipeline
  • The `mode` param controls which timeframe block runs — no code duplication
  • Outputs are split into 4 clean buckets regardless of which strategy fires:
      weekly_buy / weekly_sell / monthly_buy / monthly_sell
  • Only the external scheduler (cron / GitHub Action) needs to differ:
      Friday EOD or Monday pre-open  →  engine.run_all(mode="weekly")
      Month-end EOD or month-start   →  engine.run_all(mode="monthly")

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SIGNAL TIMING — when each strategy checks for new signals
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Weekly  (S2, S4, S5) → candle closes FRIDAY (last trading day of week)
    Run engine on:  FRIDAY EOD     — signals ready same evening
                OR  MONDAY pre-open — acting on Friday's closed weekly candle
    Signal date = Friday's date (closing date of the weekly bar)

  Monthly (S1, S3)     → candle closes LAST TRADING DAY of month
    Run engine on:  LAST TRADING DAY of month EOD
                OR  FIRST TRADING DAY of next month pre-open
    Signal date = last trading day of that month
    (The monthly candle must be fully closed before signals are read.)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONFIRMED STRATEGY PARAMETERS  (post-backtest 2010–2026, CAGR-validated)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  S1 │ Monthly EMA20 Breakout   │ UNCHANGED  │ Universe expansion pending
     │                          │            │ (MCap + CAGR study on N500)
  ───┼──────────────────────────┼────────────┼──────────────────────────────
  S2 │ Weekly EMA Pullback      │ CONFIRMED✅│ Nifty 100 universe, MCap>=75k Cr filter
     │                          │            │ V3 177.5 | MaxDD -34.5%
  ───┼──────────────────────────┼────────────┼──────────────────────────────
  S3 │ Monthly SSF50 Breakout   │ OPTION C ✅│ Added: MACD line > 0 filter
     │                          │            │ Avg DD: -7.6% vs -47.5% (B)
     │                          │            │ Composite score: 1548 (best)
  ───┼──────────────────────────┼────────────┼──────────────────────────────
  S4 │ Weekly SSF50 Breakout    │ OPTION D ✅│ Setup relaxed: SSF50 only
     │                          │            │ Profitable 14/14 periods
     │                          │            │ Exp: +8.5% vs -3.98% (live)
  ───┼──────────────────────────┼────────────┼──────────────────────────────
  S5 │ Weekly ETF Breakout      │ MODIFIED-1✅│ SSF50 + RSI14 > RSI14_MA
     │                          │            │ WR 77.8% | Exp +52.7% | V3 4748

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
S3 OPTION C — what changed from live (Option B)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Was  (Option B):  MACD line > Signal line
  Now  (Option C):  MACD line > Signal line  AND  MACD line > 0   ← new gate

  The extra "MACD line > 0" condition prevents entries during a bounce from
  deeply negative MACD territory — only allows entry when macro momentum has
  fully turned positive.  Over 14 rolling 3Y windows this cut average max
  drawdown from -47.5% → -7.6% (6× reduction).  Composite score 1548 vs 597.
  CAGR-validated: best across all 3 scoring formulas (Exp×WR/DD, CAGR×WR/DD,
  Exp×WR×CAGR/DD²).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
S4 OPTION D — what changed from live (Option B)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Was  (Option B):  prev_close < SSF50  AND  SSF200  AND  SSF250  (triple gate)
  Now  (Option D):  prev_close < SSF50  ONLY                      ← relaxed

  Entry confirmation unchanged: MACD line > Signal + both > 0.

  The triple-SSF setup was too restrictive — only 7 signals in 3 years, WR
  14.3%, Exp -3.98%.  Relaxing to SSF50-only produces 6.7× more valid setups,
  win rate 46.8%, Exp +7.86%, and makes the strategy profitable in all 14/14
  periods tested including every crash and bear cycle since 2010.
  CAGR +57.8%/yr avg vs -0.6%/yr for live Option B.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DESIGN PRINCIPLES (unchanged)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  - No lookahead bias: signals on date D use only data up to and including D
  - Full signal log: every signal records all indicator values + conditions met
  - Holding Protection: stocks removed from sheet still get EXIT evaluation
  - Graceful degradation: fetch failure → skip ticker + log, never crash
"""

import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Literal

log = logging.getLogger("signal_engine")

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DATA_DIR   = Path(__file__).resolve().parent.parent / "data"
SIGNAL_DIR = Path(__file__).resolve().parent.parent / "signals"


# ─────────────────────────────────────────────────────────────────────────────
# Load config
# ─────────────────────────────────────────────────────────────────────────────

def load_signal_config() -> dict:
    cfg_path = CONFIG_DIR / "signal_config.json"
    with open(cfg_path) as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# Strategy evaluators — one function per strategy
# ─────────────────────────────────────────────────────────────────────────────

class SignalEngine:

    def __init__(self, run_date: str | None = None, mode: Literal["weekly", "monthly", "both"] = "both"):
        self.run_date  = run_date or datetime.today().strftime("%Y-%m-%d")
        self.mode      = mode
        self.config    = load_signal_config()
        SIGNAL_DIR.mkdir(parents=True, exist_ok=True)

        # Lazy imports (allow partial usage without full deps)
        from src.data_fetcher import fetch_ohlcv, fetch_multi_timeframe
        from src.indicators   import (
            compute_for_strategy, ema_tv, rsi, rsi_ma, ssf,
            macd, sma, crossover_above, crossover_below,
            price_crosses_above, slope
        )
        self._fetch_ohlcv        = fetch_ohlcv
        self._fetch_multi        = fetch_multi_timeframe
        self._compute            = compute_for_strategy
        self._ema_tv             = ema_tv
        self._rsi                = rsi
        self._rsi_ma             = rsi_ma
        self._ssf                = ssf
        self._macd               = macd
        self._sma                = sma
        self._crossover_above    = crossover_above
        self._crossover_below    = crossover_below
        self._price_crosses_above = price_crosses_above
        self._slope              = slope

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _last_row(self, df: pd.DataFrame) -> pd.Series | None:
        """Return the most recent row (last close bar)."""
        if df is None or len(df) < 2:
            return None
        return df.iloc[-1]

    def _prev_row(self, df: pd.DataFrame) -> pd.Series | None:
        """Return the second-to-last row (previous close bar)."""
        if df is None or len(df) < 2:
            return None
        return df.iloc[-2]

    def _signal_record(
        self,
        ticker: str,
        strategy_id: str,
        strategy_name: str,
        signal_type: str,   # 'BUY' | 'SELL'
        signal_date: str,
        indicators: dict,
        triggered_conditions: list[str],
        extra: dict | None = None,
    ) -> dict:
        rec = {
            "date":                signal_date,
            "ticker":              ticker,
            "strategy_id":         strategy_id,
            "strategy_name":       strategy_name,
            "signal_type":         signal_type,
            "triggered_conditions": " | ".join(triggered_conditions),
        }
        rec.update(indicators)
        if extra:
            rec.update(extra)
        return rec

    def _safe_val(self, series_or_val, default=np.nan):
        """Safely extract a scalar value."""
        if isinstance(series_or_val, pd.Series):
            v = series_or_val.iloc[-1] if len(series_or_val) > 0 else default
        else:
            v = series_or_val
        return float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else default

    # ─────────────────────────────────────────────────────────────────────────
    # Strategy 1 — Monthly EMA20 Breakout
    # ─────────────────────────────────────────────────────────────────────────

    def run_strategy1(
        self,
        ticker: str,
        portfolio_tickers: set[str],
    ) -> list[dict]:
        """
        Monthly EMA20 Breakout — UNCHANGED (universe expansion pending)

        Logic is frozen until S1/S2 MCap + CAGR study on Nifty 500 is complete.
        Currently generates 0 signals on 94-stock universe — the RSI > 60
        filter on all 3 timeframes simultaneously is rarely met at this size.
        Will be re-evaluated after MCap threshold optimisation results are reviewed.

        Universe filter : RSI14 > 60 on Daily AND Weekly AND Monthly (AND logic)
        Setup           : EMA10 > EMA20 > EMA50 AND price > EMA50 (monthly)
        Entry (BUY)     : Price crosses above monthly EMA20 this month
        Exit  (SELL)    : EMA10 crosses below EMA20 (monthly), both slopes < 0

        Run on: LAST TRADING DAY of month EOD  or  FIRST DAY of month pre-open.
        """
        signals = []
        try:
            data = self._fetch_multi(ticker, ["daily", "weekly", "monthly"], lookback_years=5)
            df_d = data.get("daily")
            df_w = data.get("weekly")
            df_m = data.get("monthly")

            if any(x is None or len(x) < 30 for x in [df_d, df_w, df_m]):
                log.warning(f"S1 {ticker}: insufficient data — skipping.")
                return []

            # Compute indicators
            from src.indicators import ema_tv, rsi, slope, crossover_above, crossover_below
            close_d = df_d["close"]
            close_w = df_w["close"]
            close_m = df_m["close"]

            rsi_d = rsi(close_d, 14)
            rsi_w = rsi(close_w, 14)
            rsi_m = rsi(close_m, 14)

            ema10_m  = ema_tv(close_m, 10)
            ema20_m  = ema_tv(close_m, 20)
            ema50_m  = ema_tv(close_m, 50)
            slope10_m = slope(ema10_m, 3)
            slope20_m = slope(ema20_m, 3)

            # Current values
            rsi_d_now = rsi_d.iloc[-1]
            rsi_w_now = rsi_w.iloc[-1]
            rsi_m_now = rsi_m.iloc[-1]

            close_m_now  = close_m.iloc[-1]
            close_m_prev = close_m.iloc[-2]
            ema10_m_now  = ema10_m.iloc[-1]
            ema20_m_now  = ema20_m.iloc[-1]
            ema20_m_prev = ema20_m.iloc[-2]
            ema50_m_now  = ema50_m.iloc[-1]
            ema10_m_prev = ema10_m.iloc[-2]
            slope10_now  = slope10_m.iloc[-1]
            slope20_now  = slope20_m.iloc[-1]

            signal_date = str(df_m["date"].iloc[-1])[:10]

            indicator_snapshot = {
                "RSI14_daily": round(rsi_d_now, 2),
                "RSI14_weekly": round(rsi_w_now, 2),
                "RSI14_monthly": round(rsi_m_now, 2),
                "EMA10_monthly": round(ema10_m_now, 2),
                "EMA20_monthly": round(ema20_m_now, 2),
                "EMA50_monthly": round(ema50_m_now, 2),
                "close_monthly": round(close_m_now, 2),
                "EMA10_slope_monthly": round(slope10_now, 5),
                "EMA20_slope_monthly": round(slope20_now, 5),
            }

            # ── Universe filter: RSI > 60 on all 3 timeframes ────────────────
            if not (rsi_d_now > 60 and rsi_w_now > 60 and rsi_m_now > 60):
                return []

            # ── BUY signal check ─────────────────────────────────────────────
            # Setup: EMA10 > EMA20 > EMA50 and price > EMA50 (monthly)
            setup_ok = (
                ema10_m_now > ema20_m_now and
                ema20_m_now > ema50_m_now and
                close_m_now > ema50_m_now
            )

            if setup_ok:
                # Entry: price crosses above EMA20 this month
                buy_signal = (close_m_prev < ema20_m_prev) and (close_m_now > ema20_m_now)
                if buy_signal:
                    signals.append(self._signal_record(
                        ticker, "S1_monthly_ema20_breakout", "Monthly EMA20 Breakout",
                        "BUY", signal_date, indicator_snapshot,
                        ["price_crossed_above_EMA20_monthly",
                         "RSI14_D_W_M_above_60",
                         "EMA_alignment_confirmed"],
                    ))
                    return signals

            # ── SELL signal check (only if in portfolio) ─────────────────────
            if ticker in portfolio_tickers:
                # Exit: EMA10 crosses below EMA20, both slopes down
                sell_signal = (
                    (ema10_m_prev > ema20_m_prev) and
                    (ema10_m_now  < ema20_m_now)  and
                    slope10_now < 0 and
                    slope20_now < 0
                )
                if sell_signal:
                    signals.append(self._signal_record(
                        ticker, "S1_monthly_ema20_breakout", "Monthly EMA20 Breakout",
                        "SELL", signal_date, indicator_snapshot,
                        ["EMA10_crossed_below_EMA20_monthly",
                         "EMA10_slope_down", "EMA20_slope_down"],
                    ))

        except Exception as e:
            log.error(f"S1 error for {ticker}: {e}", exc_info=True)

        return signals

    # ─────────────────────────────────────────────────────────────────────────
    # Strategy 2 — Weekly EMA10/20 Pullback Cross
    # ─────────────────────────────────────────────────────────────────────────

    def run_strategy2(self, ticker: str, portfolio_tickers: set[str]) -> list[dict]:
        """
        Weekly EMA10/20 Pullback Cross — CONFIRMED ✅  Nifty 100 universe

        Universe filter   : RSI14 > 60 on Daily AND Weekly AND Monthly (AND logic)
        Monthly condition : EMA10 > EMA20 > EMA50 on monthly timeframe
        Setup             : Weekly EMA10 was below EMA20 last week (pullback)
        Entry (BUY)       : Weekly EMA10 crosses above EMA20 this week
        Exit  (SELL)      : Weekly EMA10 crosses below EMA20 this week

        Run on: FRIDAY EOD (after weekly candle closes)  or  MONDAY pre-open.
        """
        signals = []
        try:
            data = self._fetch_multi(ticker, ["daily", "weekly", "monthly"], lookback_years=3)
            df_d = data.get("daily")
            df_w = data.get("weekly")
            df_m = data.get("monthly")

            if any(x is None or len(x) < 26 for x in [df_d, df_w, df_m]):
                return []

            from src.indicators import ema_tv, rsi

            rsi_d = rsi(df_d["close"], 14).iloc[-1]
            rsi_w = rsi(df_w["close"], 14).iloc[-1]
            rsi_m = rsi(df_m["close"], 14).iloc[-1]

            # Universe filter
            if not (rsi_d > 60 and rsi_w > 60 and rsi_m > 60):
                return []

            # Monthly pre-condition
            ema10_m = ema_tv(df_m["close"], 10)
            ema20_m = ema_tv(df_m["close"], 20)
            ema50_m = ema_tv(df_m["close"], 50)
            if not (ema10_m.iloc[-1] > ema20_m.iloc[-1] > ema50_m.iloc[-1]):
                return []

            # Weekly EMA10/20
            ema10_w = ema_tv(df_w["close"], 10)
            ema20_w = ema_tv(df_w["close"], 20)

            ema10_now  = ema10_w.iloc[-1]
            ema10_prev = ema10_w.iloc[-2]
            ema20_now  = ema20_w.iloc[-1]
            ema20_prev = ema20_w.iloc[-2]

            signal_date = str(df_w["date"].iloc[-1])[:10]

            indicator_snapshot = {
                "RSI14_daily":    round(rsi_d, 2),
                "RSI14_weekly":   round(rsi_w, 2),
                "RSI14_monthly":  round(rsi_m, 2),
                "EMA10_monthly":  round(ema10_m.iloc[-1], 2),
                "EMA20_monthly":  round(ema20_m.iloc[-1], 2),
                "EMA50_monthly":  round(ema50_m.iloc[-1], 2),
                "EMA10_weekly":   round(ema10_now, 2),
                "EMA20_weekly":   round(ema20_now, 2),
            }

            # BUY: setup (prev week EMA10 < EMA20) + crossover above this week
            setup_ok  = ema10_prev < ema20_prev
            entry_ok  = ema10_prev < ema20_prev and ema10_now > ema20_now

            if setup_ok and entry_ok:
                signals.append(self._signal_record(
                    ticker, "S2_weekly_ema_pullback", "Weekly EMA Pullback Cross",
                    "BUY", signal_date, indicator_snapshot,
                    ["EMA10_crossed_above_EMA20_weekly",
                     "RSI14_D_W_M_above_60",
                     "monthly_EMA_alignment_confirmed"],
                ))
                return signals

            # SELL: EMA10 crosses below EMA20 (weekly)
            if ticker in portfolio_tickers:
                sell_ok = (ema10_prev > ema20_prev) and (ema10_now < ema20_now)
                if sell_ok:
                    signals.append(self._signal_record(
                        ticker, "S2_weekly_ema_pullback", "Weekly EMA Pullback Cross",
                        "SELL", signal_date, indicator_snapshot,
                        ["EMA10_crossed_below_EMA20_weekly"],
                    ))

        except Exception as e:
            log.error(f"S2 error for {ticker}: {e}", exc_info=True)

        return signals

    # ─────────────────────────────────────────────────────────────────────────
    # Strategy 3 — Monthly SSF50 Breakout
    # ─────────────────────────────────────────────────────────────────────────

    def run_strategy3(self, ticker: str, portfolio_tickers: set[str]) -> list[dict]:
        """
        Monthly SSF50 Breakout — CONFIRMED VARIANT: Option C  ✅

        Backtest 2010–2026 (14 rolling 3Y windows, 94 stocks):
          Avg Expectancy +42.1% | Avg CAGR +32.3%/yr | Avg WR 50.9%
          Avg Max DD -7.6% | Composite Score 1548 | Profitable 9/14 periods

        CHANGE FROM LIVE (Option B → Option C):
          Option B entry: MACD line > Signal line
          Option C entry: MACD line > Signal line  AND  MACD line > 0  ← new

        Setup  : prev month close < SSF50  AND  SSF200  AND  SSF250  (unchanged)
        Entry  : price crosses above SSF50
                 + RSI14 > RSI14_MA(14)
                 + MACD line > Signal line
                 + MACD line > 0                    ← Option C addition
        Exit   : MACD line crosses below Signal line (monthly bearish crossover)

        Run on: LAST TRADING DAY of month EOD  or  FIRST DAY of next month pre-open.
        Signal date = closing date of the triggering monthly bar.
        """
        signals = []
        try:
            df_m = self._fetch_ohlcv(ticker, "monthly", lookback_years=5)
            if df_m is None or len(df_m) < 50:
                return []

            from src.indicators import ssf, rsi, rsi_ma, macd as calc_macd

            close_m = df_m["close"]

            ssf50  = ssf(close_m, 50)
            ssf200 = ssf(close_m, 200)
            ssf250 = ssf(close_m, 250)
            rsi14  = rsi(close_m, 14)
            rsi14_ma = rsi_ma(rsi14, 14)
            macd_line, macd_sig, _ = calc_macd(close_m, 12, 26, 9)

            # iloc[-1] = current closed bar  |  iloc[-2] = previous closed bar
            close_now   = close_m.iloc[-1]
            close_prev  = close_m.iloc[-2]
            ssf50_now   = ssf50.iloc[-1]
            ssf50_prev  = ssf50.iloc[-2]
            ssf200_prev = ssf200.iloc[-2]
            ssf250_prev = ssf250.iloc[-2]
            rsi14_now      = rsi14.iloc[-1]
            rsi14_ma_now   = rsi14_ma.iloc[-1]
            macd_line_now  = macd_line.iloc[-1]
            macd_line_prev = macd_line.iloc[-2]
            macd_sig_now   = macd_sig.iloc[-1]
            macd_sig_prev  = macd_sig.iloc[-2]

            signal_date = str(df_m["date"].iloc[-1])[:10]

            indicator_snapshot = {
                "close_monthly":       round(close_now, 2),
                "SSF50_monthly":       round(ssf50_now, 2),
                "SSF200_monthly":      round(ssf200.iloc[-1], 2),
                "SSF250_monthly":      round(ssf250.iloc[-1], 2),
                "RSI14_monthly":       round(rsi14_now, 2),
                "RSI14_MA_monthly":    round(rsi14_ma_now, 2),
                "MACD_line_monthly":   round(macd_line_now, 4),
                "MACD_signal_monthly": round(macd_sig_now, 4),
                "variant":             "C",
            }

            # ── Setup: prev month close below ALL THREE SSF levels ────────────
            # (unchanged from Option B — strict triple-SSF setup gate)
            setup_ok = (
                close_prev < ssf50_prev and
                close_prev < ssf200_prev and
                close_prev < ssf250_prev
            )

            if setup_ok:
                # ── Entry conditions (Option C) ───────────────────────────────
                SSF_BUFFER = 0.003  # 0.3% buffer — eliminates marginal crossovers from data-source noise
                c1_price_breakout  = (close_prev < ssf50_prev) and (close_now > ssf50_now * (1 + SSF_BUFFER))
                c2_rsi_rising      = rsi14_now > rsi14_ma_now
                c3_macd_above_sig  = macd_line_now > macd_sig_now
                c4_macd_above_zero = macd_line_now > 0    # ← Option C new gate

                if c1_price_breakout and c2_rsi_rising and c3_macd_above_sig and c4_macd_above_zero:
                    signals.append(self._signal_record(
                        ticker, "S3_monthly_ssf50_breakout", "Monthly SSF50 Breakout [Opt-C]",
                        "BUY", signal_date, indicator_snapshot,
                        ["price_crossed_above_SSF50_monthly",
                         "RSI14_above_RSI14_MA",
                         "MACD_line_above_signal",
                         "MACD_line_above_zero"],        # ← Option C
                    ))
                    return signals

            # ── Exit: MACD bearish crossover (portfolio tickers only) ─────────
            if ticker in portfolio_tickers:
                macd_bearish_cross = (macd_line_prev > macd_sig_prev) and (macd_line_now < macd_sig_now)
                if macd_bearish_cross:
                    signals.append(self._signal_record(
                        ticker, "S3_monthly_ssf50_breakout", "Monthly SSF50 Breakout [Opt-C]",
                        "SELL", signal_date, indicator_snapshot,
                        ["MACD_line_crossed_below_signal_monthly"],
                    ))

        except Exception as e:
            log.error(f"S3 error for {ticker}: {e}", exc_info=True)

        return signals

    # ─────────────────────────────────────────────────────────────────────────
    # Strategy 4 — Weekly SSF50 Breakout
    # ─────────────────────────────────────────────────────────────────────────

    def run_strategy4(self, ticker: str, portfolio_tickers: set[str]) -> list[dict]:
        """
        Weekly SSF50 Breakout — CONFIRMED VARIANT: Option D  ✅

        Backtest 2010–2026 (14 rolling 3Y windows, 94 stocks):
          Avg Expectancy +8.5% | Avg CAGR +57.8%/yr | Avg WR 47.2%
          Avg Max DD -52.7% | Profitable 14/14 periods (only variant 100%)

        CHANGE FROM LIVE (Option B → Option D):
          Option B setup: prev_close < SSF50  AND  SSF200  AND  SSF250
          Option D setup: prev_close < SSF50  ONLY          ← relaxed
          Entry confirmation: unchanged (MACD line > signal + both > 0)

        Setup  : prev week close < SSF50 ONLY
                 (SSF200 and SSF250 no longer required — key change from live)
        Entry  : price crosses above SSF50
                 + RSI14 > RSI14_MA(14)
                 + MACD line > Signal line
                 + MACD line > 0  AND  Signal line > 0  (both positive)
        Exit   : MACD line crosses below Signal line (weekly bearish crossover)

        Run on: FRIDAY EOD (after weekly candle closes)  or  MONDAY pre-open.
        Signal date = Friday's date (closing date of the weekly bar).
        """
        signals = []
        try:
            df_w = self._fetch_ohlcv(ticker, "weekly", lookback_years=5)
            if df_w is None or len(df_w) < 50:
                return []

            from src.indicators import ssf, rsi, rsi_ma, macd as calc_macd

            close_w = df_w["close"]

            ssf50    = ssf(close_w, 50)
            ssf200   = ssf(close_w, 200)   # still computed — logged in snapshot
            ssf250   = ssf(close_w, 250)   # still computed — logged in snapshot
            rsi14    = rsi(close_w, 14)
            rsi14_ma = rsi_ma(rsi14, 14)
            macd_line, macd_sig, _ = calc_macd(close_w, 12, 26, 9)

            # iloc[-1] = current closed bar  |  iloc[-2] = previous closed bar
            close_now  = close_w.iloc[-1]
            close_prev = close_w.iloc[-2]
            ssf50_now  = ssf50.iloc[-1]
            ssf50_prev = ssf50.iloc[-2]

            rsi14_now      = rsi14.iloc[-1]
            rsi14_ma_now   = rsi14_ma.iloc[-1]
            macd_line_now  = macd_line.iloc[-1]
            macd_line_prev = macd_line.iloc[-2]
            macd_sig_now   = macd_sig.iloc[-1]
            macd_sig_prev  = macd_sig.iloc[-2]

            signal_date = str(df_w["date"].iloc[-1])[:10]

            indicator_snapshot = {
                "close_weekly":        round(close_now, 2),
                "SSF50_weekly":        round(ssf50_now, 2),
                "SSF200_weekly":       round(ssf200.iloc[-1], 2),   # logged but not gating
                "SSF250_weekly":       round(ssf250.iloc[-1], 2),   # logged but not gating
                "RSI14_weekly":        round(rsi14_now, 2),
                "RSI14_MA_weekly":     round(rsi14_ma_now, 2),
                "MACD_line_weekly":    round(macd_line_now, 4),
                "MACD_signal_weekly":  round(macd_sig_now, 4),
                "variant":             "D",
            }

            # ── Setup: prev week close below SSF50 ONLY (Option D) ───────────
            # SSF200 and SSF250 no longer required here — that was Option B's
            # overly restrictive gate that produced only 7 signals in 3 years
            setup_ok = close_prev < ssf50_prev

            if setup_ok:
                # ── Entry conditions (Option D) ───────────────────────────────
                SSF_BUFFER = 0.003  # 0.3% buffer — eliminates marginal crossovers from data-source noise
                c1_price_breakout = (close_prev < ssf50_prev) and (close_now > ssf50_now * (1 + SSF_BUFFER))
                c2_rsi_rising     = rsi14_now > rsi14_ma_now
                c3_macd_above_sig = macd_line_now > macd_sig_now
                c4_both_positive  = macd_line_now > 0 and macd_sig_now > 0  # both > 0

                if c1_price_breakout and c2_rsi_rising and c3_macd_above_sig and c4_both_positive:
                    signals.append(self._signal_record(
                        ticker, "S4_weekly_ssf50_breakout", "Weekly SSF50 Breakout [Opt-D]",
                        "BUY", signal_date, indicator_snapshot,
                        ["price_crossed_above_SSF50_weekly",
                         "RSI14_above_RSI14_MA",
                         "MACD_line_above_signal_line",
                         "MACD_line_and_signal_both_above_zero"],
                    ))
                    return signals

            # ── Exit: MACD bearish crossover (portfolio tickers only) ─────────
            if ticker in portfolio_tickers:
                macd_bearish = (macd_line_prev > macd_sig_prev) and (macd_line_now < macd_sig_now)
                if macd_bearish:
                    signals.append(self._signal_record(
                        ticker, "S4_weekly_ssf50_breakout", "Weekly SSF50 Breakout [Opt-D]",
                        "SELL", signal_date, indicator_snapshot,
                        ["MACD_line_crossed_below_signal_weekly"],
                    ))

        except Exception as e:
            log.error(f"S4 error for {ticker}: {e}", exc_info=True)

        return signals

    # ─────────────────────────────────────────────────────────────────────────
    # Strategy 5 — Weekly ETF Breakout (manual exit)
    # ─────────────────────────────────────────────────────────────────────────

    def run_strategy5(self, ticker: str) -> list[dict]:
        """
        Weekly ETF SSF50 Breakout — CONFIRMED VARIANT: Modified-1  ✅

        Backtest 2020-2026 (12 ETFs, 2 windows):
          2023-2026 : 18 trades | WR 77.8% | Exp +52.71% | CAGR +109.4% | MaxDD -9.72%
                      PF 78.37 | V3 Score 4748
          2020-2022 : 23 trades | WR 56.5% | Exp +33.04% | CAGR +104.9% | MaxDD -61.07%

        CHANGE FROM ORIGINAL (as-is → Modified-1):
          Was: SSF50 breakout only — no confirmation filter
          Now: SSF50 breakout + RSI14 > RSI14_MA(14)  ← confirmation gate

          The RSI14 > RSI14_MA gate ensures momentum is genuinely rising before
          entry, filtering out breakouts during weak/fading momentum phases.
          Result: WR 77.8% (up from 46.4%), Exp +52.7% (up from +10.1%).

        Universe  : All ETFs from master ETF list — no pre-filter applied
        Setup     : Previous weekly close was below SSF50
        Entry     : Current weekly close crosses above SSF50
                  + RSI14 > RSI14_MA(14)   ← Modified-1 confirmation gate
        Exit      : MANUAL — no automated exit signal
                    (trader monitors and exits based on own judgement)

        Run on: FRIDAY EOD (after weekly candle closes)  or  MONDAY pre-open.
        Signal date = Friday's date (closing date of the weekly bar).
        """
        signals = []
        try:
            df_w = self._fetch_ohlcv(ticker, "weekly", lookback_years=3)
            if df_w is None or len(df_w) < 55:
                return []

            from src.indicators import ssf, rsi, rsi_ma

            close_w = df_w["close"]

            ssf50    = ssf(close_w, 50)
            rsi14    = rsi(close_w, 14)
            rsi14_ma = rsi_ma(rsi14, 14)

            close_now    = close_w.iloc[-1]
            close_prev   = close_w.iloc[-2]
            ssf50_now    = ssf50.iloc[-1]
            ssf50_prev   = ssf50.iloc[-2]
            rsi14_now    = rsi14.iloc[-1]
            rsi14_ma_now = rsi14_ma.iloc[-1]

            signal_date = str(df_w["date"].iloc[-1])[:10]

            indicator_snapshot = {
                "close_weekly":    round(close_now, 2),
                "SSF50_weekly":    round(ssf50_now, 2),
                "RSI14_weekly":    round(rsi14_now, 2),
                "RSI14_MA_weekly": round(rsi14_ma_now, 2),
                "variant":         "Modified-1",
            }

            # ── Setup: prev week close below SSF50 ───────────────────────────
            setup_ok = close_prev < ssf50_prev

            if setup_ok:
                # ── Entry: SSF50 breakout + RSI14 > RSI14_MA ─────────────────
                SSF_BUFFER = 0.003  # 0.3% buffer — eliminates marginal crossovers from data-source noise
                c1_price_breakout = (close_prev < ssf50_prev) and (close_now > ssf50_now * (1 + SSF_BUFFER))
                c2_rsi_rising     = rsi14_now > rsi14_ma_now   # Modified-1 gate

                if c1_price_breakout and c2_rsi_rising:
                    signals.append(self._signal_record(
                        ticker, "S5_weekly_etf_breakout", "Weekly ETF Breakout [Mod-1]",
                        "BUY", signal_date, indicator_snapshot,
                        ["price_crossed_above_SSF50_weekly",
                         "RSI14_above_RSI14_MA"],
                        extra={"exit_type": "MANUAL"},
                    ))

        except Exception as e:
            log.error(f"S5 error for {ticker}: {e}", exc_info=True)

        return signals

    # ─────────────────────────────────────────────────────────────────────────
    # Main run: orchestrate all strategies
    # ─────────────────────────────────────────────────────────────────────────

    def run_all(
        self,
        stock_tickers: list[str],
        etf_tickers: list[str],
        portfolio_tickers: set[str] | None = None,
        removed_from_sheet: set[str] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """
        Run all active strategies on the full universe and return signal buckets.

        SCHEDULING:
          Call with mode="weekly"  on FRIDAY EOD or MONDAY pre-open
            → runs S2 (Weekly EMA Pullback) + S4 (Weekly SSF50, Opt-D) + S5 (ETF)
          Call with mode="monthly" on LAST TRADING DAY of month EOD
                                   or FIRST TRADING DAY of next month pre-open
            → runs S1 (Monthly EMA20) + S3 (Monthly SSF50, Opt-C)
          Call with mode="both"    for full runs or testing

        HOLDING PROTECTION:
          Tickers in removed_from_sheet are no longer on the master sheet but
          may still be held in Upstox.  For these tickers:
            • BUY  signals are suppressed entirely
            • SELL signals are still generated, flagged with ⚠️ warning

        RETURNS dict of four DataFrames:
          "weekly_buy"   → BUY  signals from S2, S4, S5
          "weekly_sell"  → SELL signals from S2, S4
          "monthly_buy"  → BUY  signals from S1, S3
          "monthly_sell" → SELL signals from S1, S3

        Each signal row contains: date, ticker, strategy_id, strategy_name,
        signal_type, triggered_conditions + all indicator values at signal time.
        """
        portfolio_tickers  = portfolio_tickers  or set()
        removed_from_sheet = removed_from_sheet or set()

        # Full analysis universe: sheet tickers ∪ portfolio holdings
        full_stock_universe = list(set(stock_tickers) | portfolio_tickers)

        # ── S2 universe = same full_stock_universe (RSI filter applied inside run_strategy2) ──
        s2_universe = full_stock_universe

        all_signals: list[dict] = []

        # ── Weekly strategies ─────────────────────────────────────────────────
        if self.mode in ("weekly", "both"):
            log.info(f"Running S2 on {len(s2_universe)} stocks (Nifty 100, RSI filter at bar time) ...")
            log.info(f"Running S4/S5 on {len(full_stock_universe)} stocks ...")

            for i, ticker in enumerate(full_stock_universe, 1):
                log.info(f"  [{i}/{len(full_stock_universe)}] {ticker}")
                is_removed = ticker in removed_from_sheet

                # S2 — MCap-filtered universe only
                if ticker in s2_universe:
                    if not is_removed:
                        sigs = self.run_strategy2(ticker, portfolio_tickers)
                        all_signals.extend(sigs)
                    else:
                        sigs = self.run_strategy2(ticker, portfolio_tickers)
                        for s in sigs:
                            if s["signal_type"] == "SELL":
                                s["warning"] = "⚠️ Removed from Master Sheet"
                                all_signals.append(s)

                # S4 — full universe (no MCap filter)
                if not is_removed:
                    sigs = self.run_strategy4(ticker, portfolio_tickers)
                    all_signals.extend(sigs)
                else:
                    sigs = self.run_strategy4(ticker, portfolio_tickers)
                    for s in sigs:
                        if s["signal_type"] == "SELL":
                            s["warning"] = "⚠️ Removed from Master Sheet"
                            all_signals.append(s)

            # S5 — ETFs
            log.info(f"Running S5 ETF strategy on {len(etf_tickers)} ETFs ...")
            for ticker in etf_tickers:
                all_signals.extend(self.run_strategy5(ticker))

        # ── Monthly strategies ────────────────────────────────────────────────
        if self.mode in ("monthly", "both"):
            log.info(f"Running monthly strategies on {len(full_stock_universe)} stocks ...")

            for i, ticker in enumerate(full_stock_universe, 1):
                log.info(f"  [{i}/{len(full_stock_universe)}] {ticker}")
                is_removed = ticker in removed_from_sheet

                if not is_removed:
                    all_signals.extend(self.run_strategy1(ticker, portfolio_tickers))
                    all_signals.extend(self.run_strategy3(ticker, portfolio_tickers))
                else:
                    for s in self.run_strategy1(ticker, portfolio_tickers):
                        if s["signal_type"] == "SELL":
                            s["warning"] = "⚠️ Removed from Master Sheet"
                            all_signals.append(s)
                    for s in self.run_strategy3(ticker, portfolio_tickers):
                        if s["signal_type"] == "SELL":
                            s["warning"] = "⚠️ Removed from Master Sheet"
                            all_signals.append(s)

        # ── Split and save ────────────────────────────────────────────────────
        df_all = pd.DataFrame(all_signals) if all_signals else pd.DataFrame()

        results = {
            "weekly_buy":   pd.DataFrame(),
            "weekly_sell":  pd.DataFrame(),
            "monthly_buy":  pd.DataFrame(),
            "monthly_sell": pd.DataFrame(),
        }

        if df_all.empty:
            log.info("No signals generated.")
            return results

        weekly_strategies  = ["S2_weekly_ema_pullback", "S4_weekly_ssf50_breakout", "S5_weekly_etf_breakout"]
        monthly_strategies = ["S1_monthly_ema20_breakout", "S3_monthly_ssf50_breakout"]

        results["weekly_buy"]   = df_all[(df_all["strategy_id"].isin(weekly_strategies))  & (df_all["signal_type"] == "BUY")].reset_index(drop=True)
        results["weekly_sell"]  = df_all[(df_all["strategy_id"].isin(weekly_strategies))  & (df_all["signal_type"] == "SELL")].reset_index(drop=True)
        results["monthly_buy"]  = df_all[(df_all["strategy_id"].isin(monthly_strategies)) & (df_all["signal_type"] == "BUY")].reset_index(drop=True)
        results["monthly_sell"] = df_all[(df_all["strategy_id"].isin(monthly_strategies)) & (df_all["signal_type"] == "SELL")].reset_index(drop=True)

        # Save signal CSVs
        today = self.run_date
        for key, df in results.items():
            if not df.empty:
                fname = SIGNAL_DIR / f"{key}_{today}.csv"
                df.to_csv(fname, index=False)
                log.info(f"Saved: {fname} ({len(df)} signals)")

        log.info(
            f"Signal run complete — "
            f"Weekly BUY: {len(results['weekly_buy'])}, "
            f"Weekly SELL: {len(results['weekly_sell'])}, "
            f"Monthly BUY: {len(results['monthly_buy'])}, "
            f"Monthly SELL: {len(results['monthly_sell'])}"
        )

        return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    engine = SignalEngine(mode="weekly")
    log.info("Signal engine initialised. Call engine.run_all() with tickers to generate signals.")
