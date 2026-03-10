"""
dashboard.py
------------
6-page Streamlit dashboard for the Nifty 500 Quant Signal Engine.

Pages:
  1 — Live Signals 📡
  2 — Strategy Configuration ⚙️
  3 — Portfolio & Holdings 💼
  4 — Master Universe 📋  (live Google Sheet view)
  5 — Backtest 📊
  6 — Alerts & Automation 🔔

Run: streamlit run dashboard.py
"""

import sys
import json
import logging
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import os

log = logging.getLogger("dashboard")

# ── Inject Streamlit secrets into os.environ so all modules can read them ─────
try:
    for _key in ["GOOGLE_SHEETS_CREDENTIALS", "UPSTOX_TOKEN", "UPSTOX_API_KEY",
                 "GMAIL_USER", "GMAIL_PASS", "RECIPIENT_EMAIL"]:
        if _key in st.secrets and _key not in os.environ:
            os.environ[_key] = str(st.secrets[_key])
except Exception:
    pass

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Nifty 500 Signal Engine",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS — dark professional theme ──────────────────────────────────────
st.markdown("""
<style>
  /* Base */
  html, body, [class*="css"] {
    background-color: #0f1117 !important;
    color: #e0e0e0 !important;
    font-family: 'Inter', sans-serif;
  }
  .stApp { background-color: #0f1117; }

  /* Sidebar */
  section[data-testid="stSidebar"] {
    background-color: #13131f !important;
    border-right: 1px solid #1e1e2e;
  }

  /* Metric cards */
  [data-testid="metric-container"] {
    background: #1a1a2e;
    border: 1px solid #2a2a4e;
    border-radius: 8px;
    padding: 12px;
  }

  /* Tables */
  .dataframe { background: #13131f !important; color: #e0e0e0 !important; }

  /* Buttons */
  .stButton > button {
    background: #7c83fd;
    color: white;
    border: none;
    border-radius: 6px;
    font-weight: 600;
  }
  .stButton > button:hover { background: #5c63dd; }

  /* Tab styling */
  .stTabs [data-baseweb="tab-list"] { background: #13131f; border-radius: 8px; }
  .stTabs [data-baseweb="tab"] { color: #aaa; }
  .stTabs [aria-selected="true"] { color: #7c83fd !important; }

  /* Signal badges */
  .buy-badge  { background:#00e676;color:#000;padding:2px 8px;border-radius:4px;font-weight:bold;font-size:12px; }
  .sell-badge { background:#ff5252;color:#fff;padding:2px 8px;border-radius:4px;font-weight:bold;font-size:12px; }
  .warn-badge { background:#ffd740;color:#000;padding:2px 8px;border-radius:4px;font-weight:bold;font-size:11px; }
</style>
""", unsafe_allow_html=True)

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parent
DATA_DIR   = ROOT / "data"
SIGNAL_DIR = ROOT / "signals"
CONFIG_DIR = ROOT / "config"


# ── Data loaders ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_universe() -> tuple[pd.DataFrame, pd.DataFrame]:
    stock_path = DATA_DIR / "stock_universe.csv"
    etf_path   = DATA_DIR / "etf_universe.csv"
    stocks = pd.read_csv(stock_path) if stock_path.exists() else pd.DataFrame()
    etfs   = pd.read_csv(etf_path)   if etf_path.exists()   else pd.DataFrame()
    return stocks, etfs


@st.cache_data(ttl=300)
def load_latest_signals() -> dict[str, pd.DataFrame]:
    result = {}
    for key in ["weekly_buy", "weekly_sell", "monthly_buy", "monthly_sell"]:
        files = sorted(SIGNAL_DIR.glob(f"{key}_*.csv"), reverse=True)
        if files:
            result[key] = pd.read_csv(files[0])
        else:
            result[key] = pd.DataFrame()
    return result


@st.cache_data(ttl=300)
def load_universe_changes() -> pd.DataFrame:
    path = DATA_DIR / "universe_changes.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


@st.cache_data(ttl=60)
def load_portfolio() -> pd.DataFrame:
    path = DATA_DIR / "portfolio_snapshot.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


@st.cache_data(ttl=3600)
def load_signal_config() -> dict:
    path = CONFIG_DIR / "signal_config.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


# ── Sidebar navigation ─────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📊 Nifty 500\nSignal Engine")
    st.divider()

    page = st.radio(
        "Navigate",
        ["📡 Live Signals",
         "⚙️ Strategy Config",
         "💼 Portfolio",
         "📋 Master Universe",
         "📊 Backtest",
         "🔔 Alerts & Automation"],
        label_visibility="collapsed",
    )

    st.divider()
    stocks, etfs = load_universe()
    fetch_time = ""
    if not stocks.empty and "_fetched_at" in stocks.columns:
        fetch_time = stocks["_fetched_at"].iloc[0]

    st.markdown(f"**Universe**")
    st.markdown(f"🏢 Stocks: `{len(stocks)}`")
    st.markdown(f"📈 ETFs:   `{len(etfs)}`")
    if fetch_time:
        st.markdown(f"🕐 Synced: `{fetch_time[:16]}`")

    st.divider()
    if st.button("🔄 Sync Universe Now"):
        with st.spinner("Fetching Google Sheet ..."):
            try:
                from src.universe_loader import run as refresh
                summary = refresh()
                st.success(f"✅ Synced: {summary['stock_count']} stocks, {summary['etf_count']} ETFs")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Sync failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — LIVE SIGNALS
# ═══════════════════════════════════════════════════════════════════════════════

if page == "📡 Live Signals":
    st.title("📡 Live Signals")

    signals = load_latest_signals()
    portfolio = load_portfolio()
    portfolio_tickers = set(portfolio["ticker"].tolist()) if not portfolio.empty else set()

    # Summary metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Weekly BUY",   len(signals["weekly_buy"]))
    c2.metric("Weekly SELL",  len(signals["weekly_sell"]))
    c3.metric("Monthly BUY",  len(signals["monthly_buy"]))
    c4.metric("Monthly SELL", len(signals["monthly_sell"]))

    # Removed holdings warning
    changes = load_universe_changes()
    if not changes.empty:
        removed = changes[changes["change_type"] == "REMOVED"]["ticker"].tolist()
        held_removed = [t for t in removed if t in portfolio_tickers]
        if held_removed:
            st.error(f"⚠️ **Holdings removed from master sheet but still held:** {', '.join(held_removed)}")

    # Strategy filter
    all_sigs = pd.concat([
        signals["weekly_buy"],  signals["weekly_sell"],
        signals["monthly_buy"], signals["monthly_sell"],
    ], ignore_index=True)

    if all_sigs.empty:
        st.info("No signals found. Run the signal engine or check back on Friday.")
    else:
        strategies = ["All"] + sorted(all_sigs["strategy_name"].unique().tolist()) if "strategy_name" in all_sigs.columns else ["All"]
        sig_type   = st.selectbox("Signal Type", ["All", "BUY", "SELL"])
        strategy   = st.selectbox("Strategy",    strategies)

        filtered = all_sigs.copy()
        if sig_type != "All":
            filtered = filtered[filtered["signal_type"] == sig_type]
        if strategy != "All" and "strategy_name" in filtered.columns:
            filtered = filtered[filtered["strategy_name"] == strategy]

        # Highlight portfolio holdings
        if "ticker" in filtered.columns and portfolio_tickers:
            filtered["in_portfolio"] = filtered["ticker"].apply(
                lambda t: "💼" if t in portfolio_tickers else ""
            )

        st.dataframe(
            filtered,
            use_container_width=True,
            hide_index=True,
        )

        # Chart popup
        st.subheader("📈 Chart Viewer")
        if "ticker" in filtered.columns and not filtered.empty:
            selected_ticker = st.selectbox("Select ticker for chart", filtered["ticker"].unique())
            tf = st.radio("Timeframe", ["weekly", "monthly", "daily"], horizontal=True)

            if st.button("Load Chart"):
                with st.spinner(f"Loading {selected_ticker} ({tf}) ..."):
                    try:
                        from src.data_fetcher import fetch_ohlcv
                        from src.indicators   import compute_all

                        df_chart = fetch_ohlcv(selected_ticker, tf, lookback_years=2)
                        if df_chart is not None:
                            df_chart = compute_all(df_chart, tf)

                            fig = make_subplots(
                                rows=3, cols=1,
                                shared_xaxes=True,
                                row_heights=[0.6, 0.2, 0.2],
                                vertical_spacing=0.03,
                            )

                            # Candlestick
                            fig.add_trace(go.Candlestick(
                                x=df_chart["date"], open=df_chart["open"],
                                high=df_chart["high"], low=df_chart["low"],
                                close=df_chart["close"], name="Price",
                                increasing_line_color="#00e676",
                                decreasing_line_color="#ff5252",
                            ), row=1, col=1)

                            # EMA overlays
                            for ema_col, color in [("EMA10","#7c83fd"),("EMA20","#ffd740"),("EMA50","#ff9800")]:
                                if ema_col in df_chart.columns:
                                    fig.add_trace(go.Scatter(
                                        x=df_chart["date"], y=df_chart[ema_col],
                                        name=ema_col, line=dict(color=color, width=1.2),
                                    ), row=1, col=1)

                            # SSF50
                            if "SSF50" in df_chart.columns:
                                fig.add_trace(go.Scatter(
                                    x=df_chart["date"], y=df_chart["SSF50"],
                                    name="SSF50", line=dict(color="#00bcd4", width=1.5, dash="dot"),
                                ), row=1, col=1)

                            # RSI
                            if "RSI14" in df_chart.columns:
                                fig.add_trace(go.Scatter(
                                    x=df_chart["date"], y=df_chart["RSI14"],
                                    name="RSI14", line=dict(color="#7c83fd", width=1.2),
                                ), row=2, col=1)
                                fig.add_hline(y=60, line_dash="dash", line_color="#00e676", row=2, col=1)
                                fig.add_hline(y=40, line_dash="dash", line_color="#ff5252", row=2, col=1)

                            # MACD
                            if "MACD_line" in df_chart.columns:
                                fig.add_trace(go.Scatter(
                                    x=df_chart["date"], y=df_chart["MACD_line"],
                                    name="MACD", line=dict(color="#00e676", width=1),
                                ), row=3, col=1)
                                fig.add_trace(go.Scatter(
                                    x=df_chart["date"], y=df_chart["MACD_signal"],
                                    name="Signal", line=dict(color="#ff9800", width=1),
                                ), row=3, col=1)
                                fig.add_trace(go.Bar(
                                    x=df_chart["date"], y=df_chart["MACD_hist"],
                                    name="Hist", marker_color="#7c83fd", opacity=0.5,
                                ), row=3, col=1)

                            # Mark BUY/SELL signals on chart
                            ticker_sigs = filtered[filtered["ticker"] == selected_ticker]
                            for _, sig in ticker_sigs.iterrows():
                                sig_date = sig.get("date", "")
                                sig_type_val = sig.get("signal_type", "")
                                color_sig = "#00e676" if sig_type_val == "BUY" else "#ff5252"
                                symbol_sig = "triangle-up" if sig_type_val == "BUY" else "triangle-down"
                                match_row = df_chart[df_chart["date"].astype(str).str.startswith(sig_date[:10])]
                                if not match_row.empty:
                                    y_val = match_row["low"].iloc[0] * 0.99 if sig_type_val == "BUY" else match_row["high"].iloc[0] * 1.01
                                    fig.add_trace(go.Scatter(
                                        x=[match_row["date"].iloc[0]], y=[y_val],
                                        mode="markers",
                                        marker=dict(symbol=symbol_sig, size=14, color=color_sig),
                                        name=sig_type_val, showlegend=False,
                                    ), row=1, col=1)

                            fig.update_layout(
                                template="plotly_dark",
                                paper_bgcolor="#0f1117",
                                plot_bgcolor="#0f1117",
                                height=700,
                                title=f"{selected_ticker} — {tf.capitalize()}",
                                xaxis_rangeslider_visible=False,
                                showlegend=True,
                            )
                            st.plotly_chart(fig, use_container_width=True)
                        else:
                            st.error("Could not load price data.")
                    except Exception as e:
                        st.error(f"Chart error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — STRATEGY CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "⚙️ Strategy Config":
    st.title("⚙️ Strategy Configuration")

    cfg = load_signal_config()
    strategies = cfg.get("strategies", [])

    for strat in strategies:
        with st.expander(f"{'🟢' if strat.get('enabled') else '🔴'} {strat['name']} ({strat['signal_timeframe'].upper()})", expanded=False):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**Description:** {strat.get('description','')}")
                st.markdown(f"**Type:** `{strat.get('type','')}` | **Universe:** `{strat.get('universe','')}`")
                st.markdown(f"**Strategy ID:** `{strat['id']}`")

            with col2:
                enabled = st.toggle("Enabled", value=strat.get("enabled", True), key=f"toggle_{strat['id']}")

            st.divider()

            # Show entry/exit in readable form
            if strat.get("entry_signal"):
                st.markdown("**Entry Signal:**")
                entry = strat["entry_signal"]
                for cond in entry.get("conditions", []):
                    st.markdown(f"  - {cond.get('description', str(cond))}")

            if strat.get("exit_signal"):
                st.markdown("**Exit Signal:**")
                exit_sig = strat["exit_signal"]
                for cond in exit_sig.get("conditions", []):
                    st.markdown(f"  - {cond.get('description', str(cond))}")
                if exit_sig.get("type") == "manual":
                    st.markdown("  - **Manual exit only** (no automated exit signal)")

            if strat.get("notes"):
                st.markdown("**Notes:**")
                for note in strat["notes"]:
                    st.markdown(f"  ℹ️ {note}")

    st.divider()
    st.subheader("📝 Add / Edit Strategy in Plain English")
    st.info("Describe your new strategy in plain English below and the system will parse it into a structured definition.")
    user_strategy_text = st.text_area("Strategy description", height=150,
        placeholder="e.g. On the weekly chart, buy when EMA10 crosses above EMA50 and RSI14 is above 50 ...")
    if st.button("Parse Strategy"):
        if user_strategy_text.strip():
            st.warning("🚧 NLP parser (rule_parser.py) will process this. Integrate Claude API key to activate.")
        else:
            st.warning("Please enter a strategy description.")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — PORTFOLIO & HOLDINGS
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "💼 Portfolio":
    st.title("💼 Portfolio & Holdings")

    if st.button("🔄 Sync Upstox Holdings"):
        with st.spinner("Syncing portfolio ..."):
            try:
                from src.portfolio import get_portfolio_details, save_portfolio_snapshot
                df_port = get_portfolio_details()
                save_portfolio_snapshot(df_port)
                st.success(f"✅ Synced {len(df_port)} holdings.")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Sync failed: {e}")

    portfolio = load_portfolio()
    stocks, _ = load_universe()
    sheet_tickers = set(stocks["Ticker (NSE)"].tolist()) if not stocks.empty and "Ticker (NSE)" in stocks.columns else set()

    if portfolio.empty:
        st.info("No portfolio data. Click 'Sync Upstox Holdings' to load your positions.")
    else:
        # Flag removed holdings
        if "ticker" in portfolio.columns:
            portfolio["in_sheet"] = portfolio["ticker"].apply(
                lambda t: "✅" if t in sheet_tickers else "⚠️ Removed"
            )

        # Summary metrics
        if "pnl_inr" in portfolio.columns:
            total_invested = (portfolio["qty"] * portfolio["avg_cost"]).sum()
            total_current  = (portfolio["qty"] * portfolio["ltp"]).sum()
            total_pnl      = portfolio["pnl_inr"].sum()
            pnl_pct        = (total_pnl / total_invested * 100) if total_invested > 0 else 0

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Invested (₹)", f"₹{total_invested:,.0f}")
            c2.metric("Current Value (₹)", f"₹{total_current:,.0f}")
            c3.metric("Total P&L (₹)", f"₹{total_pnl:,.0f}", delta=f"{pnl_pct:.2f}%")
            c4.metric("Positions", len(portfolio))

        st.dataframe(portfolio, use_container_width=True, hide_index=True)

        removed_held = portfolio[portfolio.get("in_sheet", pd.Series(["✅"] * len(portfolio))) == "⚠️ Removed"]
        if not removed_held.empty:
            st.error(f"⚠️ **{len(removed_held)} holdings removed from master sheet:** " +
                     ", ".join(removed_held["ticker"].tolist()))


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — MASTER UNIVERSE
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "📋 Master Universe":
    st.title("📋 Master Universe")

    stocks, etfs = load_universe()
    changes = load_universe_changes()
    portfolio = load_portfolio()
    portfolio_tickers = set(portfolio["ticker"].tolist()) if not portfolio.empty else set()
    signals = load_latest_signals()
    buy_tickers = set()
    for key in ["weekly_buy", "monthly_buy"]:
        if not signals[key].empty and "ticker" in signals[key].columns:
            buy_tickers |= set(signals[key]["ticker"].tolist())

    # ── Sync status panel ─────────────────────────────────────────────────────
    fetch_time = stocks["_fetched_at"].iloc[0] if not stocks.empty and "_fetched_at" in stocks.columns else "Unknown"
    latest_change_run = changes["run_at"].iloc[-1][:16] if not changes.empty and "run_at" in changes.columns else "N/A"

    st.markdown(f"""
    <div style='background:#13131f;border-radius:8px;padding:16px;margin-bottom:16px;'>
      <span style='color:#7c83fd;font-weight:bold;'>Last synced from Google Sheet:</span>
      <span style='color:#e0e0e0;margin-left:8px;'>{fetch_time}</span>
      &nbsp;|&nbsp;
      <span style='color:#7c83fd;font-weight:bold;'>Stocks:</span>
      <span style='color:#e0e0e0;margin-left:4px;'>{len(stocks)}</span>
      &nbsp;|&nbsp;
      <span style='color:#7c83fd;font-weight:bold;'>ETFs:</span>
      <span style='color:#e0e0e0;margin-left:4px;'>{len(etfs)}</span>
      &nbsp;|&nbsp;
      <span style='color:#7c83fd;font-weight:bold;'>Last change run:</span>
      <span style='color:#e0e0e0;margin-left:4px;'>{latest_change_run}</span>
    </div>
    """, unsafe_allow_html=True)

    # Recent changes
    if not changes.empty:
        today_str = datetime.today().strftime("%Y-%m-%d")
        recent = changes[changes["run_at"].str.startswith(today_str)] if "run_at" in changes.columns else pd.DataFrame()
        if not recent.empty:
            with st.expander(f"🔄 Changes since last run ({len(recent)})", expanded=True):
                for _, row in recent.iterrows():
                    ct = row["change_type"]
                    color = "#00e676" if ct == "ADDED" else "#ff5252" if ct == "REMOVED" else "#ffd740"
                    icon  = "+" if ct == "ADDED" else "−" if ct == "REMOVED" else "~"
                    st.markdown(
                        f"<span style='color:{color};font-family:monospace;'>[{icon}] **{row['ticker']}** — {row['detail']}</span>",
                        unsafe_allow_html=True
                    )

    # Action buttons
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("🔄 Sync Now"):
            with st.spinner("Fetching Google Sheet ..."):
                try:
                    from src.universe_loader import run as refresh
                    refresh()
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Sync failed: {e}")
    with col2:
        st.link_button(
            "🔗 Open in Google Sheets",
            "https://docs.google.com/spreadsheets/d/1jTlHPIMOiXcCIFPlJcUS2NjtXh6iBdGBarO26glnFAk/",
        )

    # Tabs: Stocks | ETFs
    tab_stocks, tab_etfs = st.tabs(["🏢 Stocks", "📈 ETFs"])

    with tab_stocks:
        if stocks.empty:
            st.info("No stock data. Click 'Sync Now' to load from Google Sheet.")
        else:
            # ── Sidebar filters ───────────────────────────────────────────────
            st.markdown("**Filters**")
            fc1, fc2, fc3 = st.columns(3)

            with fc1:
                ta_filter = st.selectbox("TA Status", ["All", "BUY", "Under Observation", "Blank"])

            with fc2:
                search_q = st.text_input("Search company / ticker", placeholder="e.g. ITC")

            with fc3:
                f_score_min = st.slider("Min F-Score", 0, 9, 0)

            show_3ta   = st.checkbox("Only stocks with all 3 TA signals = YES")
            signals_only = st.checkbox("Only stocks with active BUY signal")

            # ── Apply filters ─────────────────────────────────────────────────
            df_show = stocks.copy()

            if ta_filter != "All" and "TA Status" in df_show.columns:
                if ta_filter == "Blank":
                    df_show = df_show[df_show["TA Status"].isna() | (df_show["TA Status"] == "")]
                else:
                    df_show = df_show[df_show["TA Status"].str.contains(ta_filter, na=False, case=False)]

            if search_q and "Company Name" in df_show.columns:
                mask = (
                    df_show["Company Name"].str.contains(search_q, case=False, na=False) |
                    df_show["Ticker (NSE)"].str.contains(search_q, case=False, na=False)
                )
                df_show = df_show[mask]

            if f_score_min > 0 and "F-Score" in df_show.columns:
                df_show = df_show[pd.to_numeric(df_show["F-Score"], errors="coerce") >= f_score_min]

            if show_3ta and all(c in df_show.columns for c in ["TA - SSF", "TA - MACD", "TA - RSI"]):
                df_show = df_show[
                    (df_show["TA - SSF"] == "YES") &
                    (df_show["TA - MACD"] == "YES") &
                    (df_show["TA - RSI"] == "YES")
                ]

            if signals_only and "Ticker (NSE)" in df_show.columns:
                df_show = df_show[df_show["Ticker (NSE)"].isin(buy_tickers)]

            # ── Add icons ─────────────────────────────────────────────────────
            if "Ticker (NSE)" in df_show.columns:
                df_show["Icons"] = df_show["Ticker (NSE)"].apply(
                    lambda t: ("💼 " if t in portfolio_tickers else "") +
                              ("📡 " if t in buy_tickers else "")
                )
                # Move Icons column to front
                cols = ["Icons"] + [c for c in df_show.columns if c != "Icons" and not c.startswith("_")]
                df_show = df_show[cols]

            # Remove internal columns
            display_cols = [c for c in df_show.columns if not c.startswith("_")]
            df_show = df_show[display_cols]

            st.markdown(f"**{len(df_show)} stocks** (filtered from {len(stocks)})")

            # Colour-coded dataframe
            def colour_ta_status(val):
                if str(val).strip().upper() == "BUY":
                    return "background-color:#1a3a1a;color:#00e676;"
                elif "UNDER OBSERVATION FOR BUY" in str(val).upper():
                    return "background-color:#2a2a0a;color:#ffd740;"
                elif "UNDER OBSERVATION FOR SALE" in str(val).upper():
                    return "background-color:#3a1a0a;color:#ff9800;"
                elif "UNDER OBSERVATION" in str(val).upper():
                    return "background-color:#2a2000;color:#ffd740;"
                return "background-color:#1a1a1a;color:#888;"

            def colour_ta_indicator(val):
                v = str(val).strip().upper()
                if v == "YES": return "color:#00e676;font-weight:bold;"
                if v == "NO":  return "color:#ff5252;"
                return "color:#666;"

            styled = df_show.style
            if "TA Status" in df_show.columns:
                styled = styled.applymap(colour_ta_status, subset=["TA Status"])
            for col in ["TA - SSF", "TA - MACD", "TA - RSI"]:
                if col in df_show.columns:
                    styled = styled.applymap(colour_ta_indicator, subset=[col])

            st.dataframe(styled, use_container_width=True, hide_index=True, height=600)

            # Export
            if st.button("⬇️ Export to Excel"):
                import io
                buf = io.BytesIO()
                df_show.to_excel(buf, index=False)
                st.download_button(
                    "Download Excel",
                    data=buf.getvalue(),
                    file_name=f"stock_universe_{datetime.today().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

    with tab_etfs:
        if etfs.empty:
            st.info("No ETF data loaded.")
        else:
            display_cols = [c for c in etfs.columns if not c.startswith("_")]
            if "Ticker (NSE)" in etfs.columns:
                etfs["Signal"] = etfs["Ticker (NSE)"].apply(lambda t: "📡 BUY" if t in buy_tickers else "")
            st.dataframe(etfs[display_cols], use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "📊 Backtest":
    st.title("📊 Backtest")

    st.warning("⚠️ **Survivorship bias note:** Backtests use the current Nifty 500 universe. Stocks delisted during the test period are not included. Results are indicative only.")

    cfg = load_signal_config()
    strategy_names = [s["name"] for s in cfg.get("strategies", [])]

    col1, col2, col3 = st.columns(3)
    with col1:
        selected_strategy = st.selectbox("Strategy", strategy_names)
    with col2:
        start_date = st.date_input("From", value=pd.Timestamp("2022-01-01"))
    with col3:
        end_date = st.date_input("To", value=pd.Timestamp.today())

    if st.button("▶️ Run Backtest"):
        st.info("🚧 Backtest engine (src/backtest.py) — connect to run full simulation with tax modelling, equity curve, and trade log.")
        st.markdown("""
        **Backtest will include:**
        - Interactive equity curve vs Nifty 500 benchmark
        - Bull/bear/sideways regime shading
        - STCG 20% (< 1 year) and LTCG 12.5% (> 1 year) tax modelling
        - Trade log with entry/exit dates, P&L, holding days
        - Max drawdown, CAGR, Sharpe ratio
        """)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 6 — ALERTS & AUTOMATION
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "🔔 Alerts & Automation":
    st.title("🔔 Alerts & Automation")

    st.subheader("📧 Email Configuration")
    col1, col2 = st.columns(2)
    with col1:
        st.text_input("Gmail sender",    value=os.environ.get("GMAIL_USER", ""), disabled=True)
        st.text_input("Recipient email", value=os.environ.get("RECIPIENT_EMAIL", ""), disabled=True)
    with col2:
        if st.button("📨 Send Test Email"):
            try:
                from src.email_report import send_weekly_report
                result = send_weekly_report(
                    results={"weekly_buy": pd.DataFrame(), "weekly_sell": pd.DataFrame(),
                             "monthly_buy": pd.DataFrame(), "monthly_sell": pd.DataFrame()},
                    universe_summary={"stock_count": 0, "etf_count": 0},
                    portfolio_tickers=set(),
                    removed_tickers=set(),
                    run_date=datetime.today().strftime("%Y-%m-%d"),
                )
                st.success("✅ Test email sent!") if result else st.error("❌ Email failed — check GMAIL credentials in environment.")
            except Exception as e:
                st.error(f"Error: {e}")

    st.divider()
    st.subheader("⏰ Run Schedule")

    schedule_data = {
        "Workflow":     ["weekly_signals.yml", "weekend_universe_refresh.yml"],
        "Trigger":      ["Every Friday 9:00 PM IST", "Every Saturday 6:00 AM IST"],
        "Action":       ["Fetch Sheet → Signals → Email → Commit", "Fetch Sheet → Commit (dashboard refresh)"],
        "Last Month":   ["Last Friday: also runs S1 + S3 monthly strategies", "No signal run — universe only"],
    }
    st.dataframe(pd.DataFrame(schedule_data), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("🔑 Required GitHub Secrets")
    secrets_data = {
        "Secret Name":  ["UPSTOX_TOKEN", "UPSTOX_API_KEY", "GMAIL_USER", "GMAIL_PASS",
                         "RECIPIENT_EMAIL", "GOOGLE_SHEETS_CREDENTIALS"],
        "Purpose":      ["Upstox access token (refresh daily)", "Upstox API key",
                         "Gmail sender address", "Gmail app password",
                         "Email recipient address", "Google service account JSON for Sheets API fallback"],
        "Required":     ["✅ Yes", "✅ Yes", "✅ Yes", "✅ Yes", "✅ Yes", "Optional (only if sheet is private)"],
    }
    st.dataframe(pd.DataFrame(secrets_data), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("▶️ Manual Trigger")
    st.info("To manually trigger a signal run, go to your GitHub repo → Actions → Weekly Signal Run → Run workflow.")

import os  # needed for page 6
