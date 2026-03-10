"""
signal_engine.py
----------------
Runs all active strategies defined in config/signal_config.json
against the current universe (stocks + ETFs).

Design principles:
  - No lookahead bias: signals on date D use only data up to and including D
  - Full signal log: every signal records date, ticker, strategy, all indicator
    values at signal time, which conditions triggered
  - Holding Protection: stocks removed from sheet but in Upstox portfolio
    are still evaluated for EXIT signals
  - Graceful degradation: data fetch failure → skip ticker + log, never crash
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
        Monthly EMA20 Breakout on Trending Stocks.
        Requires RSI14 > 60 on D/W/M and full EMA alignment on monthly.
        Entry: price crosses above monthly EMA20.
        Exit:  EMA10 crosses below EMA20 (monthly), both slopes down.
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
        Weekly EMA10/20 pullback entry within Strategy 1's monthly uptrend window.
        Universe filter: RSI14 > 60 on D/W/M.
        Monthly pre-condition: EMA10 > EMA20 > EMA50 on monthly.
        Setup: EMA10 < EMA20 last week.
        Entry: EMA10 crosses above EMA20 this week.
        Exit:  EMA10 crosses below EMA20 this week.
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

            # SELL: EMA10 crosses below EMA20 this week
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
        Monthly SSF50 breakout with MACD and RSI confirmation.
        No universe filter (all master list stocks eligible).
        Setup: prev month close below SSF50, SSF200, SSF250.
        Entry: price crosses above SSF50 + RSI14 > SMA(RSI14,14) + MACD > Signal.
        Exit:  MACD crosses below Signal (monthly).
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
            macd_line, macd_sig, macd_hist = calc_macd(close_m, 12, 26, 9)

            close_now  = close_m.iloc[-1]
            close_prev = close_m.iloc[-2]
            ssf50_now  = ssf50.iloc[-1]
            ssf50_prev = ssf50.iloc[-2]
            ssf200_prev = ssf200.iloc[-2]
            ssf250_prev = ssf250.iloc[-2]
            rsi14_now  = rsi14.iloc[-1]
            rsi14_ma_now = rsi14_ma.iloc[-1]
            macd_line_now  = macd_line.iloc[-1]
            macd_line_prev = macd_line.iloc[-2]
            macd_sig_now   = macd_sig.iloc[-1]
            macd_sig_prev  = macd_sig.iloc[-2]

            signal_date = str(df_m["date"].iloc[-1])[:10]

            indicator_snapshot = {
                "close_monthly":      round(close_now, 2),
                "SSF50_monthly":      round(ssf50_now, 2),
                "RSI14_monthly":      round(rsi14_now, 2),
                "RSI14_MA_monthly":   round(rsi14_ma_now, 2),
                "MACD_line_monthly":  round(macd_line_now, 4),
                "MACD_signal_monthly":round(macd_sig_now, 4),
            }

            # ── Setup: prev month close below all three SSFs ──────────────────
            setup_ok = (
                close_prev < ssf50_prev and
                close_prev < ssf200_prev and
                close_prev < ssf250_prev
            )

            if setup_ok:
                # BUY: price crosses above SSF50 AND RSI > RSI_MA AND MACD > Signal
                price_breakout = (close_prev < ssf50_prev) and (close_now > ssf50_now)
                rsi_confirm    = rsi14_now > rsi14_ma_now      # strictly greater
                macd_confirm   = macd_line_now > macd_sig_now

                if price_breakout and rsi_confirm and macd_confirm:
                    signals.append(self._signal_record(
                        ticker, "S3_monthly_ssf50_breakout", "Monthly SSF50 Breakout",
                        "BUY", signal_date, indicator_snapshot,
                        ["price_crossed_above_SSF50_monthly",
                         "RSI14_above_RSI14_MA",
                         "MACD_line_above_signal"],
                    ))
                    return signals

            # SELL: MACD crosses below signal (only if in portfolio)
            if ticker in portfolio_tickers:
                macd_bearish_cross = (macd_line_prev > macd_sig_prev) and (macd_line_now < macd_sig_now)
                if macd_bearish_cross:
                    signals.append(self._signal_record(
                        ticker, "S3_monthly_ssf50_breakout", "Monthly SSF50 Breakout",
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
        Weekly SSF50 breakout + RSI above its MA + MACD positive crossover.
        No universe filter.
        Setup: prev week close below SSF50, SSF200, SSF250.
        Entry: price crosses above SSF50 + RSI14 > SMA(RSI14,14) +
               MACD Line crosses above Signal (this week) + both > 0.
        Exit:  MACD crosses below Signal (weekly).
        """
        signals = []
        try:
            df_w = self._fetch_ohlcv(ticker, "weekly", lookback_years=5)
            if df_w is None or len(df_w) < 50:
                return []

            from src.indicators import ssf, rsi, rsi_ma, macd as calc_macd

            close_w = df_w["close"]

            ssf50  = ssf(close_w, 50)
            ssf200 = ssf(close_w, 200)
            ssf250 = ssf(close_w, 250)
            rsi14  = rsi(close_w, 14)
            rsi14_ma = rsi_ma(rsi14, 14)
            macd_line, macd_sig, _ = calc_macd(close_w, 12, 26, 9)

            close_now  = close_w.iloc[-1]
            close_prev = close_w.iloc[-2]

            ssf50_now  = ssf50.iloc[-1]
            ssf50_prev = ssf50.iloc[-2]
            ssf200_prev = ssf200.iloc[-2]
            ssf250_prev = ssf250.iloc[-2]

            rsi14_now    = rsi14.iloc[-1]
            rsi14_ma_now = rsi14_ma.iloc[-1]

            macd_line_now  = macd_line.iloc[-1]
            macd_line_prev = macd_line.iloc[-2]
            macd_sig_now   = macd_sig.iloc[-1]
            macd_sig_prev  = macd_sig.iloc[-2]

            signal_date = str(df_w["date"].iloc[-1])[:10]

            indicator_snapshot = {
                "close_weekly":       round(close_now, 2),
                "SSF50_weekly":       round(ssf50_now, 2),
                "RSI14_weekly":       round(rsi14_now, 2),
                "RSI14_MA_weekly":    round(rsi14_ma_now, 2),
                "MACD_line_weekly":   round(macd_line_now, 4),
                "MACD_signal_weekly": round(macd_sig_now, 4),
            }

            # Setup: prev week close below all three SSFs
            setup_ok = (
                close_prev < ssf50_prev and
                close_prev < ssf200_prev and
                close_prev < ssf250_prev
            )

            if setup_ok:
                price_breakout  = (close_prev < ssf50_prev) and (close_now > ssf50_now)
                rsi_confirm     = rsi14_now > rsi14_ma_now
                macd_cross_up   = (macd_line_prev < macd_sig_prev) and (macd_line_now > macd_sig_now)
                macd_both_pos   = macd_line_now > 0 and macd_sig_now > 0

                if price_breakout and rsi_confirm and macd_cross_up and macd_both_pos:
                    signals.append(self._signal_record(
                        ticker, "S4_weekly_ssf50_breakout", "Weekly SSF50 Breakout",
                        "BUY", signal_date, indicator_snapshot,
                        ["price_crossed_above_SSF50_weekly",
                         "RSI14_above_RSI14_MA",
                         "MACD_crossed_above_signal_this_week",
                         "MACD_line_and_signal_above_zero"],
                    ))
                    return signals

            # SELL: MACD bearish crossover (only if in portfolio)
            if ticker in portfolio_tickers:
                macd_bearish = (macd_line_prev > macd_sig_prev) and (macd_line_now < macd_sig_now)
                if macd_bearish:
                    signals.append(self._signal_record(
                        ticker, "S4_weekly_ssf50_breakout", "Weekly SSF50 Breakout",
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
        Two independent weekly ETF signals.
        Signal A: price crosses above SSF50 (setup: prev week < SSF50).
        Signal B: EMA10 crosses above EMA20 (independent, no SSF dependency).
        No automated exit — manual only.
        """
        signals = []
        try:
            df_w = self._fetch_ohlcv(ticker, "weekly", lookback_years=3)
            if df_w is None or len(df_w) < 55:
                return []

            from src.indicators import ssf, ema_tv

            close_w = df_w["close"]

            ssf50  = ssf(close_w, 50)
            ema10  = ema_tv(close_w, 10)
            ema20  = ema_tv(close_w, 20)

            close_now   = close_w.iloc[-1]
            close_prev  = close_w.iloc[-2]
            ssf50_now   = ssf50.iloc[-1]
            ssf50_prev  = ssf50.iloc[-2]
            ema10_now   = ema10.iloc[-1]
            ema10_prev  = ema10.iloc[-2]
            ema20_now   = ema20.iloc[-1]
            ema20_prev  = ema20.iloc[-2]

            signal_date = str(df_w["date"].iloc[-1])[:10]

            indicator_snapshot = {
                "close_weekly": round(close_now, 2),
                "SSF50_weekly": round(ssf50_now, 2),
                "EMA10_weekly": round(ema10_now, 2),
                "EMA20_weekly": round(ema20_now, 2),
            }

            # ── Signal A: SSF50 structural breakout ──────────────────────────
            setup_a = close_prev < ssf50_prev
            entry_a = setup_a and (close_now > ssf50_now)
            if entry_a:
                signals.append(self._signal_record(
                    ticker, "S5_weekly_etf_breakout", "Weekly ETF Breakout",
                    "BUY", signal_date, indicator_snapshot,
                    ["price_crossed_above_SSF50_weekly"],
                    extra={"entry_signal": "A_SSF50_Breakout", "exit_type": "MANUAL"},
                ))

            # ── Signal B: EMA10/20 crossover (independent) ───────────────────
            setup_b = ema10_prev < ema20_prev
            entry_b = setup_b and (ema10_now > ema20_now)
            if entry_b:
                signals.append(self._signal_record(
                    ticker, "S5_weekly_etf_breakout", "Weekly ETF Breakout",
                    "BUY", signal_date, indicator_snapshot,
                    ["EMA10_crossed_above_EMA20_weekly"],
                    extra={"entry_signal": "B_EMA_Crossover", "exit_type": "MANUAL"},
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
        Run all active strategies on the full universe.

        Holding Protection Rule (Component 1D):
          - removed_from_sheet tickers → EXIT signals ONLY, flagged as ⚠️

        Returns:
            {
                "weekly_buy":   DataFrame,
                "weekly_sell":  DataFrame,
                "monthly_buy":  DataFrame,
                "monthly_sell": DataFrame,
            }
        """
        portfolio_tickers  = portfolio_tickers  or set()
        removed_from_sheet = removed_from_sheet or set()

        # Full analysis universe: sheet tickers ∪ portfolio holdings
        full_stock_universe = list(set(stock_tickers) | portfolio_tickers)

        all_signals: list[dict] = []

        # ── Weekly strategies ─────────────────────────────────────────────────
        if self.mode in ("weekly", "both"):
            log.info(f"Running weekly strategies on {len(full_stock_universe)} stocks ...")

            for i, ticker in enumerate(full_stock_universe, 1):
                log.info(f"  [{i}/{len(full_stock_universe)}] {ticker}")
                is_removed = ticker in removed_from_sheet

                # S2 — skip BUY signals for removed stocks
                if not is_removed:
                    sigs = self.run_strategy2(ticker, portfolio_tickers)
                    all_signals.extend(sigs)
                else:
                    # EXIT only
                    sigs = self.run_strategy2(ticker, portfolio_tickers)
                    for s in sigs:
                        if s["signal_type"] == "SELL":
                            s["warning"] = "⚠️ Removed from Master Sheet"
                            all_signals.append(s)

                # S4
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
