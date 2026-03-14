"""
dashboard.py
------------
6-page Streamlit dashboard for the Nifty 500 Quant Signal Engine.

Pages:
  1 — Live Signals 📡
  2 — Strategy Configuration ⚙️
  3 — Portfolio & Holdings 💼
  4 — Master Universe 📋
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

# ── Inject Streamlit secrets into os.environ ──────────────────────────────────
try:
    for _key in ["GOOGLE_SHEETS_CREDENTIALS", "UPSTOX_TOKEN", "UPSTOX_API_KEY",
                 "UPSTOX_API_SECRET", "UPSTOX_REDIRECT_URI", "UPSTOX_REFRESH_TOKEN",
                 "UPSTOX_TOKEN_EXPIRY", "GMAIL_USER", "GMAIL_PASS", "RECIPIENT_EMAIL"]:
        if _key in st.secrets and _key not in os.environ:
            os.environ[_key] = str(st.secrets[_key])
except Exception:
    pass

# ── Handle Upstox OAuth callback (?code=AUTH_CODE in URL) ─────────────────────
_qp = st.query_params
if "code" in _qp:
    _auth_code = _qp["code"]
    try:
        from src.upstox_auth import exchange_code_for_tokens
        _tokens = exchange_code_for_tokens(_auth_code)
        st.success("✅ Upstox connected! Copy these values to your Streamlit secrets:")
        _lines = [
            'UPSTOX_TOKEN         = "' + _tokens["access_token"]  + '"',
            'UPSTOX_REFRESH_TOKEN = "' + _tokens["refresh_token"] + '"',
            'UPSTOX_TOKEN_EXPIRY  = "' + _tokens["expires_at"]    + '"',
        ]
        st.code(chr(10).join(_lines), language="toml")
        st.info("After adding to secrets, redeploy the app and you will be fully connected.")
        st.stop()
    except Exception as _e:
        st.error(f"OAuth callback failed: {_e}")
        st.stop()

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Nifty 500 Signal Engine",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Design system: clean light/neutral professional theme ─────────────────────
# Palette:
#   Background:  #F7F8FA  (off-white, easy on eyes)
#   Surface:     #FFFFFF  (card backgrounds)
#   Border:      #E2E6ED
#   Text primary:#14181F  (near-black)
#   Text secondary:#5A6478
#   Accent:      #2563EB  (clear blue)
#   BUY green:   #16A34A
#   SELL red:    #DC2626
#   Warning:     #D97706

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap');

  html, body, [class*="css"] {
    background-color: #F7F8FA !important;
    color: #14181F !important;
    font-family: 'DM Sans', sans-serif !important;
  }
  .stApp { background-color: #F7F8FA !important; }

  /* ── Sidebar ── */
  section[data-testid="stSidebar"] {
    background-color: #14181F !important;
    border-right: none !important;
  }
  section[data-testid="stSidebar"] * {
    color: #E2E6ED !important;
  }
  section[data-testid="stSidebar"] .stRadio label {
    color: #CBD2DC !important;
    font-size: 14px !important;
    padding: 6px 0 !important;
  }
  section[data-testid="stSidebar"] .stRadio label:hover {
    color: #FFFFFF !important;
  }
  section[data-testid="stSidebar"] hr {
    border-color: #2A3040 !important;
  }

  /* ── Metric cards ── */
  [data-testid="metric-container"] {
    background: #FFFFFF !important;
    border: 1px solid #E2E6ED !important;
    border-radius: 10px !important;
    padding: 16px !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06) !important;
  }
  [data-testid="metric-container"] label {
    color: #5A6478 !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    letter-spacing: 0.5px !important;
    text-transform: uppercase !important;
  }
  [data-testid="metric-container"] [data-testid="stMetricValue"] {
    color: #14181F !important;
    font-size: 28px !important;
    font-weight: 700 !important;
  }

  /* ── Page title ── */
  h1 {
    color: #14181F !important;
    font-size: 24px !important;
    font-weight: 700 !important;
    letter-spacing: -0.3px !important;
    padding-bottom: 4px !important;
  }
  h2, h3 {
    color: #14181F !important;
    font-weight: 600 !important;
  }

  /* ── Dataframe / table ── */
  .stDataFrame {
    border: 1px solid #E2E6ED !important;
    border-radius: 10px !important;
    overflow: hidden !important;
  }
  .stDataFrame thead th {
    background: #F0F2F7 !important;
    color: #5A6478 !important;
    font-size: 11px !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.5px !important;
  }
  .stDataFrame tbody td {
    color: #14181F !important;
    font-size: 13px !important;
    font-family: 'DM Mono', monospace !important;
  }
  .stDataFrame tbody tr:hover {
    background: #F0F5FF !important;
  }

  /* ── Buttons ── */
  .stButton > button {
    background: #2563EB !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 13px !important;
    padding: 8px 18px !important;
    box-shadow: 0 1px 3px rgba(37,99,235,0.3) !important;
  }
  .stButton > button:hover {
    background: #1D4ED8 !important;
    box-shadow: 0 2px 6px rgba(37,99,235,0.4) !important;
  }

  /* ── Tabs ── */
  .stTabs [data-baseweb="tab-list"] {
    background: #FFFFFF !important;
    border-bottom: 2px solid #E2E6ED !important;
    border-radius: 0 !important;
    gap: 0 !important;
  }
  .stTabs [data-baseweb="tab"] {
    color: #5A6478 !important;
    font-weight: 500 !important;
    font-size: 14px !important;
    padding: 10px 20px !important;
    border-bottom: 2px solid transparent !important;
    margin-bottom: -2px !important;
  }
  .stTabs [aria-selected="true"] {
    color: #2563EB !important;
    border-bottom: 2px solid #2563EB !important;
    font-weight: 700 !important;
  }

  /* ── Expander ── */
  .streamlit-expanderHeader {
    background: #FFFFFF !important;
    border: 1px solid #E2E6ED !important;
    border-radius: 8px !important;
    color: #14181F !important;
    font-weight: 600 !important;
  }
  .streamlit-expanderContent {
    background: #FFFFFF !important;
    border: 1px solid #E2E6ED !important;
    border-top: none !important;
    border-radius: 0 0 8px 8px !important;
  }

  /* ── Selectbox / inputs ── */
  .stSelectbox > div > div,
  .stTextInput > div > div > input {
    background: #FFFFFF !important;
    border: 1px solid #D1D9E6 !important;
    border-radius: 8px !important;
    color: #14181F !important;
    font-size: 13px !important;
  }

  /* ── Alert / info boxes ── */
  .stAlert {
    border-radius: 8px !important;
    font-size: 13px !important;
  }

  /* ── Badge helpers ── */
  .badge-buy  { background:#DCFCE7; color:#15803D; padding:3px 10px; border-radius:20px; font-weight:700; font-size:12px; }
  .badge-sell { background:#FEE2E2; color:#DC2626; padding:3px 10px; border-radius:20px; font-weight:700; font-size:12px; }
  .badge-warn { background:#FEF3C7; color:#B45309; padding:3px 10px; border-radius:20px; font-weight:600; font-size:11px; }
  .badge-info { background:#DBEAFE; color:#1D4ED8; padding:3px 10px; border-radius:20px; font-weight:600; font-size:11px; }

  /* ── Card component ── */
  .card {
    background: #FFFFFF;
    border: 1px solid #E2E6ED;
    border-radius: 10px;
    padding: 20px 24px;
    margin-bottom: 16px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
  }
  .card-label {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    color: #5A6478;
    margin-bottom: 6px;
  }
  .card-value {
    font-size: 22px;
    font-weight: 700;
    color: #14181F;
  }
  .card-green { border-left: 4px solid #16A34A; }
  .card-red   { border-left: 4px solid #DC2626; }
  .card-blue  { border-left: 4px solid #2563EB; }
  .card-amber { border-left: 4px solid #D97706; }

  /* ── Page header strip ── */
  .page-header {
    background: #FFFFFF;
    border-bottom: 1px solid #E2E6ED;
    padding: 16px 0 14px 0;
    margin-bottom: 24px;
  }
  .page-header h1 { margin: 0 !important; }
  .page-subtitle {
    color: #5A6478;
    font-size: 13px;
    margin-top: 2px;
  }

  /* ── Divider ── */
  hr { border-color: #E2E6ED !important; }

  /* ── Checkbox ── */
  .stCheckbox label { color: #14181F !important; font-size: 13px !important; }

  /* ── Slider ── */
  .stSlider label { color: #14181F !important; font-size: 13px !important; }

  /* ── Radio ── */
  .stRadio label { color: #14181F !important; }

  /* Remove Streamlit watermark */
  #MainMenu, footer { visibility: hidden; }
  header { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parent
DATA_DIR   = ROOT / "data"
SIGNAL_DIR = ROOT / "signals"
CONFIG_DIR = ROOT / "config"

DASHBOARD_URL = os.environ.get(
    "DASHBOARD_URL",
    "https://nifty-quant-system-updated-afqpypkjc7xdpnefsq8d3i.streamlit.app"
)

# ── Data loaders ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_universe() -> tuple[pd.DataFrame, pd.DataFrame]:
    stocks = pd.read_csv(DATA_DIR / "stock_universe.csv") if (DATA_DIR / "stock_universe.csv").exists() else pd.DataFrame()
    etfs   = pd.read_csv(DATA_DIR / "etf_universe.csv")   if (DATA_DIR / "etf_universe.csv").exists()   else pd.DataFrame()
    return stocks, etfs

@st.cache_data(ttl=300)
def load_latest_signals() -> dict[str, pd.DataFrame]:
    result = {}
    for key in ["weekly_buy", "weekly_sell", "monthly_buy", "monthly_sell"]:
        files = sorted(SIGNAL_DIR.glob(f"{key}_*.csv"), reverse=True)
        result[key] = pd.read_csv(files[0]) if files else pd.DataFrame()
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
    return json.load(open(path)) if path.exists() else {}


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style='padding: 20px 8px 16px 8px;'>
      <div style='font-size:18px;font-weight:700;color:#FFFFFF;letter-spacing:-0.3px;'>
        📊 Nifty 500
      </div>
      <div style='font-size:12px;color:#8899AA;margin-top:2px;'>Signal Engine</div>
    </div>
    """, unsafe_allow_html=True)

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

    st.markdown(f"""
    <div style='font-size:12px;color:#8899AA;line-height:2;padding:0 4px;'>
      <div><span style='color:#CBD2DC;font-weight:600;'>Stocks</span>&nbsp;&nbsp;{len(stocks)}</div>
      <div><span style='color:#CBD2DC;font-weight:600;'>ETFs</span>&nbsp;&nbsp;&nbsp;&nbsp;{len(etfs)}</div>
      {'<div><span style="color:#CBD2DC;font-weight:600;">Synced</span>&nbsp;&nbsp;' + fetch_time[:16] + '</div>' if fetch_time else ''}
    </div>
    """, unsafe_allow_html=True)

    st.divider()
    if st.button("🔄 Sync Universe"):
        with st.spinner("Fetching Google Sheet …"):
            try:
                from src.universe_loader import run as refresh
                summary = refresh()
                st.success(f"✅ {summary['stock_count']} stocks, {summary['etf_count']} ETFs")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Sync failed: {e}")


# ── Helper: section card ───────────────────────────────────────────────────────
def section(title: str, color: str = "blue"):
    st.markdown(f"""
    <div style='display:flex;align-items:center;gap:10px;margin:24px 0 14px 0;'>
      <div style='width:4px;height:20px;background:{"#16A34A" if color=="green" else "#DC2626" if color=="red" else "#D97706" if color=="amber" else "#2563EB"};border-radius:2px;'></div>
      <span style='font-size:15px;font-weight:700;color:#14181F;'>{title}</span>
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — LIVE SIGNALS
# ═══════════════════════════════════════════════════════════════════════════════

if page == "📡 Live Signals":
    st.markdown("""
    <div class='page-header'>
      <h1>📡 Live Signals</h1>
      <div class='page-subtitle'>Most recent signal run — updated every Friday after market close</div>
    </div>
    """, unsafe_allow_html=True)

    signals   = load_latest_signals()
    portfolio = load_portfolio()
    portfolio_tickers = set(portfolio["ticker"].tolist()) if not portfolio.empty else set()

    # ── Metric row ────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Weekly BUY",   len(signals["weekly_buy"]),   delta=None)
    c2.metric("Weekly SELL",  len(signals["weekly_sell"]),  delta=None)
    c3.metric("Monthly BUY",  len(signals["monthly_buy"]),  delta=None)
    c4.metric("Monthly SELL", len(signals["monthly_sell"]), delta=None)

    # ── Removed holdings warning ──────────────────────────────────────────────
    changes = load_universe_changes()
    if not changes.empty:
        removed = changes[changes["change_type"] == "REMOVED"]["ticker"].tolist()
        held_removed = [t for t in removed if t in portfolio_tickers]
        if held_removed:
            st.error(f"⚠️ **Holdings removed from master sheet but still held:** {', '.join(held_removed)}")

    # ── Signal table ──────────────────────────────────────────────────────────
    all_sigs = pd.concat([
        signals["weekly_buy"],  signals["weekly_sell"],
        signals["monthly_buy"], signals["monthly_sell"],
    ], ignore_index=True)

    if all_sigs.empty:
        st.info("No signals found. Run the signal engine or check back on Friday.")
    else:
        section("Filter Signals")
        f1, f2 = st.columns(2)
        with f1:
            sig_type = st.selectbox("Signal Type", ["All", "BUY", "SELL"])
        with f2:
            strategies = ["All"] + sorted(all_sigs["strategy_name"].unique().tolist()) if "strategy_name" in all_sigs.columns else ["All"]
            strategy = st.selectbox("Strategy", strategies)

        filtered = all_sigs.copy()
        if sig_type != "All":
            filtered = filtered[filtered["signal_type"] == sig_type]
        if strategy != "All" and "strategy_name" in filtered.columns:
            filtered = filtered[filtered["strategy_name"] == strategy]

        if "ticker" in filtered.columns and portfolio_tickers:
            filtered["in_portfolio"] = filtered["ticker"].apply(lambda t: "💼" if t in portfolio_tickers else "")

        section("Signals Table")

        # Colour signal_type column
        def style_signals(df):
            styles = pd.DataFrame("", index=df.index, columns=df.columns)
            if "signal_type" in df.columns:
                styles["signal_type"] = df["signal_type"].apply(
                    lambda v: "background-color:#DCFCE7;color:#15803D;font-weight:700;"
                    if v == "BUY" else "background-color:#FEE2E2;color:#DC2626;font-weight:700;"
                )
            return styles

        st.dataframe(
            filtered.style.apply(style_signals, axis=None),
            use_container_width=True,
            hide_index=True,
            height=400,
        )

        # ── Chart viewer ─────────────────────────────────────────────────────
        section("Chart Viewer")
        if "ticker" in filtered.columns and not filtered.empty:
            ch1, ch2, ch3 = st.columns([2, 1, 1])
            with ch1:
                selected_ticker = st.selectbox("Ticker", filtered["ticker"].unique())
            with ch2:
                tf = st.radio("Timeframe", ["weekly", "monthly", "daily"], horizontal=True)
            with ch3:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                load_chart = st.button("Load Chart")

            if load_chart:
                with st.spinner(f"Loading {selected_ticker} ({tf}) …"):
                    try:
                        from src.data_fetcher import fetch_ohlcv
                        from src.indicators   import compute_all
                        df_chart = fetch_ohlcv(selected_ticker, tf, lookback_years=2)
                        if df_chart is not None:
                            df_chart = compute_all(df_chart, tf)
                            fig = make_subplots(
                                rows=3, cols=1, shared_xaxes=True,
                                row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03,
                            )
                            fig.add_trace(go.Candlestick(
                                x=df_chart["date"], open=df_chart["open"],
                                high=df_chart["high"], low=df_chart["low"],
                                close=df_chart["close"], name="Price",
                                increasing_line_color="#16A34A",
                                decreasing_line_color="#DC2626",
                            ), row=1, col=1)
                            for ema_col, color in [("EMA10","#2563EB"),("EMA20","#D97706"),("EMA50","#7C3AED")]:
                                if ema_col in df_chart.columns:
                                    fig.add_trace(go.Scatter(
                                        x=df_chart["date"], y=df_chart[ema_col],
                                        name=ema_col, line=dict(color=color, width=1.5),
                                    ), row=1, col=1)
                            if "SSF50" in df_chart.columns:
                                fig.add_trace(go.Scatter(
                                    x=df_chart["date"], y=df_chart["SSF50"],
                                    name="SSF50", line=dict(color="#0891B2", width=1.5, dash="dot"),
                                ), row=1, col=1)
                            if "RSI14" in df_chart.columns:
                                fig.add_trace(go.Scatter(
                                    x=df_chart["date"], y=df_chart["RSI14"],
                                    name="RSI14", line=dict(color="#2563EB", width=1.5),
                                ), row=2, col=1)
                                fig.add_hline(y=60, line_dash="dash", line_color="#16A34A", row=2, col=1)
                                fig.add_hline(y=40, line_dash="dash", line_color="#DC2626", row=2, col=1)
                            if "MACD_line" in df_chart.columns:
                                fig.add_trace(go.Scatter(
                                    x=df_chart["date"], y=df_chart["MACD_line"],
                                    name="MACD", line=dict(color="#16A34A", width=1.2),
                                ), row=3, col=1)
                                fig.add_trace(go.Scatter(
                                    x=df_chart["date"], y=df_chart["MACD_signal"],
                                    name="Signal", line=dict(color="#D97706", width=1.2),
                                ), row=3, col=1)
                                fig.add_trace(go.Bar(
                                    x=df_chart["date"], y=df_chart["MACD_hist"],
                                    name="Hist", marker_color="#2563EB", opacity=0.4,
                                ), row=3, col=1)
                            # Signal markers
                            ticker_sigs = filtered[filtered["ticker"] == selected_ticker]
                            for _, sig in ticker_sigs.iterrows():
                                sig_date     = sig.get("date", "")
                                sig_type_val = sig.get("signal_type", "")
                                color_sig  = "#16A34A" if sig_type_val == "BUY" else "#DC2626"
                                symbol_sig = "triangle-up" if sig_type_val == "BUY" else "triangle-down"
                                match_row  = df_chart[df_chart["date"].astype(str).str.startswith(sig_date[:10])]
                                if not match_row.empty:
                                    y_val = match_row["low"].iloc[0] * 0.99 if sig_type_val == "BUY" else match_row["high"].iloc[0] * 1.01
                                    fig.add_trace(go.Scatter(
                                        x=[match_row["date"].iloc[0]], y=[y_val],
                                        mode="markers",
                                        marker=dict(symbol=symbol_sig, size=14, color=color_sig),
                                        name=sig_type_val, showlegend=False,
                                    ), row=1, col=1)

                            fig.update_layout(
                                template="plotly_white",
                                paper_bgcolor="#FFFFFF",
                                plot_bgcolor="#FAFBFC",
                                height=680,
                                title=dict(text=f"{selected_ticker} — {tf.capitalize()}", font=dict(size=15, color="#14181F")),
                                xaxis_rangeslider_visible=False,
                                showlegend=True,
                                legend=dict(bgcolor="#FFFFFF", bordercolor="#E2E6ED", borderwidth=1),
                                font=dict(family="DM Sans", color="#14181F"),
                            )
                            fig.update_xaxes(showgrid=True, gridcolor="#F0F2F7", linecolor="#E2E6ED")
                            fig.update_yaxes(showgrid=True, gridcolor="#F0F2F7", linecolor="#E2E6ED")
                            st.plotly_chart(fig, use_container_width=True)
                        else:
                            st.error("Could not load price data.")
                    except Exception as e:
                        st.error(f"Chart error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — STRATEGY CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "⚙️ Strategy Config":
    st.markdown("""
    <div class='page-header'>
      <h1>⚙️ Strategy Configuration</h1>
      <div class='page-subtitle'>Confirmed logic for all 5 strategies — S1 through S5</div>
    </div>
    """, unsafe_allow_html=True)

    cfg = load_signal_config()
    strategies = cfg.get("strategies", [])

    # Strategy summary table
    if strategies:
        summary_rows = []
        for s in strategies:
            summary_rows.append({
                "ID":        s["id"],
                "Name":      s["name"],
                "Timeframe": s.get("signal_timeframe", "").upper(),
                "Universe":  s.get("universe", ""),
                "Enabled":   "✅ Yes" if s.get("enabled") else "❌ No",
            })
        section("Strategy Overview")
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    section("Strategy Details")
    for strat in strategies:
        enabled_icon = "🟢" if strat.get("enabled") else "🔴"
        with st.expander(f"{enabled_icon}  {strat['name']}  ({strat.get('signal_timeframe','').upper()})", expanded=False):

            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"**{strat.get('description','')}**")
                st.markdown(
                    f"<span style='font-size:12px;color:#5A6478;'>ID: <code>{strat['id']}</code> &nbsp;|&nbsp; "
                    f"Universe: <code>{strat.get('universe','')}</code></span>",
                    unsafe_allow_html=True
                )
            with col2:
                st.toggle("Enabled", value=strat.get("enabled", True), key=f"toggle_{strat['id']}")

            st.markdown("---")
            ic1, ic2 = st.columns(2)
            with ic1:
                if strat.get("universe_filter"):
                    st.markdown("**Universe Filter**")
                    for cond in strat["universe_filter"].get("conditions", []):
                        st.markdown(f"- {cond.get('description', str(cond))}")
                if strat.get("entry_signal"):
                    st.markdown("**Entry Conditions**")
                    for cond in strat["entry_signal"].get("conditions", []):
                        st.markdown(f"- {cond.get('description', str(cond))}")
            with ic2:
                if strat.get("exit_signal"):
                    st.markdown("**Exit Conditions**")
                    exit_sig = strat["exit_signal"]
                    if exit_sig.get("type") == "manual":
                        st.markdown("- Manual exit only")
                    for cond in exit_sig.get("conditions", []):
                        st.markdown(f"- {cond.get('description', str(cond))}")
                if strat.get("notes"):
                    st.markdown("**Notes**")
                    for note in strat["notes"]:
                        st.markdown(f"- ℹ️ {note}")

    st.divider()
    section("Add / Edit Strategy in Plain English")
    st.info("Describe a new strategy and the system will parse it into a structured definition.")
    user_strategy_text = st.text_area(
        "Strategy description", height=120,
        placeholder="e.g. On the weekly chart, buy when EMA10 crosses above EMA50 and RSI14 is above 50 …"
    )
    if st.button("Parse Strategy"):
        if user_strategy_text.strip():
            st.warning("🚧 NLP parser — connect Claude API key to activate.")
        else:
            st.warning("Please enter a strategy description.")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — PORTFOLIO & HOLDINGS
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "💼 Portfolio":
    st.markdown("""
    <div class='page-header'>
      <h1>💼 Portfolio & Holdings</h1>
      <div class='page-subtitle'>Current Upstox positions synced from broker</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Upstox connection status + OAuth login ────────────────────────────────
    try:
        from src.upstox_auth import is_connected, get_login_url, credentials_complete
        _connected = is_connected()
    except Exception:
        _connected = False
        credentials_complete = lambda: False

    if not _connected:
        st.warning("⚠️ Upstox is not connected. Complete the one-time login below.")
        if credentials_complete():
            try:
                _login_url = get_login_url()
                # st.link_button opens in the same tab — works correctly inside Streamlit iframe
                st.link_button("🔗 Connect Upstox (one-time login)", _login_url,
                               type="primary", use_container_width=False)
                st.caption(
                    "Clicking the button will open Upstox login. "
                    "After login, Upstox redirects back to this app automatically."
                )
                # Also show the raw URL as fallback in case button doesn't work
                with st.expander("🔗 Or copy login URL manually"):
                    st.code(_login_url)
                    st.caption("Paste this URL in your browser if the button above doesn't redirect.")
            except Exception as _e:
                st.error(f"Cannot generate login URL: {_e}")
        else:
            st.error(
                "UPSTOX_API_KEY and UPSTOX_API_SECRET are not set in Streamlit secrets. "
                "Add them first, then redeploy."
            )
    else:
        col_sync, col_reconnect = st.columns([3, 1])
        with col_sync:
            if st.button("🔄 Sync Upstox Holdings"):
                with st.spinner("Syncing portfolio …"):
                    try:
                        from src.portfolio import get_portfolio_details, save_portfolio_snapshot
                        df_port = get_portfolio_details()
                        save_portfolio_snapshot(df_port)
                        st.success(f"✅ Synced {len(df_port)} holdings.")
                        st.cache_data.clear()
                        st.rerun()
                    except ValueError as e:
                        st.error(f"⚠️ {e}")
                    except Exception as e:
                        st.error(f"Sync failed: {e}")
        with col_reconnect:
            try:
                _reauth_url = get_login_url()
                st.link_button("🔁 Re-authenticate", _reauth_url)
            except Exception as _e:
                st.error(f"{_e}")

    portfolio = load_portfolio()
    stocks, _ = load_universe()
    sheet_tickers = set(stocks["Ticker (NSE)"].tolist()) if not stocks.empty and "Ticker (NSE)" in stocks.columns else set()

    if portfolio.empty:
        st.info("No portfolio data. Click 'Sync Upstox Holdings' to load your positions.")
    else:
        if "ticker" in portfolio.columns:
            portfolio["In Sheet"] = portfolio["ticker"].apply(
                lambda t: "✅ Active" if t in sheet_tickers else "⚠️ Removed"
            )

        if "pnl_inr" in portfolio.columns:
            total_invested = (portfolio["qty"] * portfolio["avg_cost"]).sum()
            total_current  = (portfolio["qty"] * portfolio["ltp"]).sum()
            total_pnl      = portfolio["pnl_inr"].sum()
            pnl_pct        = (total_pnl / total_invested * 100) if total_invested > 0 else 0

            section("Summary")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Invested",      f"₹{total_invested:,.0f}")
            c2.metric("Current Value", f"₹{total_current:,.0f}")
            c3.metric("Total P&L",     f"₹{total_pnl:,.0f}", delta=f"{pnl_pct:.2f}%")
            c4.metric("Positions",     len(portfolio))

        section("Holdings")

        def style_portfolio(df):
            styles = pd.DataFrame("", index=df.index, columns=df.columns)
            if "pnl_inr" in df.columns:
                styles["pnl_inr"] = df["pnl_inr"].apply(
                    lambda v: "color:#16A34A;font-weight:600;" if float(v or 0) >= 0
                    else "color:#DC2626;font-weight:600;"
                )
            if "In Sheet" in df.columns:
                styles["In Sheet"] = df["In Sheet"].apply(
                    lambda v: "color:#DC2626;font-weight:600;" if "Removed" in str(v) else "color:#16A34A;"
                )
            return styles

        st.dataframe(
            portfolio.style.apply(style_portfolio, axis=None),
            use_container_width=True, hide_index=True, height=450,
        )

        removed_held = portfolio[portfolio.get("In Sheet", pd.Series(["✅ Active"] * len(portfolio))) == "⚠️ Removed"]
        if not removed_held.empty:
            st.error(f"⚠️ **{len(removed_held)} holdings removed from master sheet:** " +
                     ", ".join(removed_held["ticker"].tolist()))


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — MASTER UNIVERSE
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "📋 Master Universe":
    st.markdown("""
    <div class='page-header'>
      <h1>📋 Master Universe</h1>
      <div class='page-subtitle'>Live view of the Google Sheet — stocks and ETFs under coverage</div>
    </div>
    """, unsafe_allow_html=True)

    stocks, etfs = load_universe()
    changes      = load_universe_changes()
    portfolio    = load_portfolio()
    portfolio_tickers = set(portfolio["ticker"].tolist()) if not portfolio.empty else set()
    signals = load_latest_signals()
    buy_tickers = set()
    for key in ["weekly_buy", "monthly_buy"]:
        if not signals[key].empty and "ticker" in signals[key].columns:
            buy_tickers |= set(signals[key]["ticker"].tolist())

    # Status bar
    fetch_time = stocks["_fetched_at"].iloc[0] if not stocks.empty and "_fetched_at" in stocks.columns else "Unknown"
    latest_change = changes["run_at"].iloc[-1][:16] if not changes.empty and "run_at" in changes.columns else "N/A"

    st.markdown(f"""
    <div style='background:#FFFFFF;border:1px solid #E2E6ED;border-radius:10px;
                padding:14px 20px;margin-bottom:20px;display:flex;gap:32px;align-items:center;
                box-shadow:0 1px 4px rgba(0,0,0,0.04);'>
      <div><span style='font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#5A6478;'>Last Synced</span>
           <div style='color:#14181F;font-size:13px;font-weight:600;margin-top:2px;'>{fetch_time[:16]}</div></div>
      <div><span style='font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#5A6478;'>Stocks</span>
           <div style='color:#14181F;font-size:20px;font-weight:700;margin-top:2px;'>{len(stocks)}</div></div>
      <div><span style='font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#5A6478;'>ETFs</span>
           <div style='color:#14181F;font-size:20px;font-weight:700;margin-top:2px;'>{len(etfs)}</div></div>
      <div><span style='font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#5A6478;'>Active BUY Signals</span>
           <div style='color:#16A34A;font-size:20px;font-weight:700;margin-top:2px;'>{len(buy_tickers)}</div></div>
      <div><span style='font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#5A6478;'>Last Change Run</span>
           <div style='color:#14181F;font-size:13px;font-weight:600;margin-top:2px;'>{latest_change}</div></div>
    </div>
    """, unsafe_allow_html=True)

    # Recent changes
    if not changes.empty:
        today_str = datetime.today().strftime("%Y-%m-%d")
        recent = changes[changes["run_at"].str.startswith(today_str)] if "run_at" in changes.columns else pd.DataFrame()
        if not recent.empty:
            with st.expander(f"🔄 Changes today ({len(recent)})", expanded=True):
                for _, row in recent.iterrows():
                    ct    = row["change_type"]
                    bg    = "#DCFCE7" if ct == "ADDED" else "#FEE2E2" if ct == "REMOVED" else "#FEF3C7"
                    color = "#15803D" if ct == "ADDED" else "#DC2626" if ct == "REMOVED" else "#B45309"
                    icon  = "+" if ct == "ADDED" else "−" if ct == "REMOVED" else "~"
                    st.markdown(
                        f"<span style='background:{bg};color:{color};font-family:DM Mono,monospace;"
                        f"padding:3px 10px;border-radius:20px;font-size:12px;font-weight:700;'>"
                        f"[{icon}] {row['ticker']}</span> "
                        f"<span style='color:#5A6478;font-size:13px;'>{row.get('detail','')}</span>",
                        unsafe_allow_html=True
                    )

    # Action buttons
    ac1, ac2 = st.columns([1, 1])
    with ac1:
        if st.button("🔄 Sync Now"):
            with st.spinner("Fetching Google Sheet …"):
                try:
                    from src.universe_loader import run as refresh
                    refresh()
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Sync failed: {e}")
    with ac2:
        st.link_button(
            "🔗 Open Google Sheet",
            "https://docs.google.com/spreadsheets/d/1jTlHPIMOiXcCIFPlJcUS2NjtXh6iBdGBarO26glnFAk/",
        )

    tab_stocks, tab_etfs = st.tabs(["🏢 Stocks", "📈 ETFs"])

    with tab_stocks:
        if stocks.empty:
            st.info("No stock data. Click 'Sync Now' to load from Google Sheet.")
        else:
            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
            fc1, fc2, fc3 = st.columns([1, 1, 1])
            with fc1:
                ta_filter = st.selectbox("TA Status", ["All", "BUY", "Under Observation", "Blank"])
            with fc2:
                search_q = st.text_input("Search", placeholder="Company or ticker …")
            with fc3:
                f_score_min = st.slider("Min F-Score", 0, 9, 0)

            col_extra1, col_extra2 = st.columns(2)
            with col_extra1:
                show_3ta = st.checkbox("All 3 TA signals = YES only")
            with col_extra2:
                signals_only = st.checkbox("Active BUY signal only")

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

            if "Ticker (NSE)" in df_show.columns:
                df_show["Flags"] = df_show["Ticker (NSE)"].apply(
                    lambda t: ("💼 " if t in portfolio_tickers else "") + ("📡 " if t in buy_tickers else "")
                )
                cols = ["Flags"] + [c for c in df_show.columns if c != "Flags" and not c.startswith("_")]
                df_show = df_show[cols]

            display_cols = [c for c in df_show.columns if not c.startswith("_")]
            df_show = df_show[display_cols]

            st.markdown(
                f"<div style='font-size:13px;color:#5A6478;margin-bottom:8px;'>"
                f"Showing <strong style='color:#14181F;'>{len(df_show)}</strong> of {len(stocks)} stocks</div>",
                unsafe_allow_html=True
            )

            def style_universe(df):
                styles = pd.DataFrame("", index=df.index, columns=df.columns)
                if "TA Status" in df.columns:
                    styles["TA Status"] = df["TA Status"].apply(
                        lambda v: "background-color:#DCFCE7;color:#15803D;font-weight:700;"
                        if str(v).strip().upper() == "BUY"
                        else "background-color:#FEF3C7;color:#B45309;"
                        if "OBSERVATION" in str(v).upper()
                        else "color:#9CA3AF;"
                    )
                for col in ["TA - SSF", "TA - MACD", "TA - RSI"]:
                    if col in df.columns:
                        styles[col] = df[col].apply(
                            lambda v: "color:#16A34A;font-weight:700;" if str(v).strip().upper() == "YES"
                            else "color:#DC2626;" if str(v).strip().upper() == "NO"
                            else "color:#9CA3AF;"
                        )
                return styles

            st.dataframe(
                df_show.style.apply(style_universe, axis=None),
                use_container_width=True, hide_index=True, height=560,
            )

            if st.button("⬇️ Export to Excel"):
                import io
                buf = io.BytesIO()
                df_show.to_excel(buf, index=False)
                st.download_button(
                    "Download Excel", data=buf.getvalue(),
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
    st.markdown("""
    <div class='page-header'>
      <h1>📊 Backtest</h1>
      <div class='page-subtitle'>Historical simulation across both 2023–2026 and 2020–2026 windows</div>
    </div>
    """, unsafe_allow_html=True)

    st.warning("⚠️ **Survivorship bias note:** Backtests use the current universe. Stocks delisted during the test period are excluded. Results are indicative only.")

    cfg = load_signal_config()
    strategy_names = [s["name"] for s in cfg.get("strategies", [])]

    section("Configure Run")
    col1, col2, col3 = st.columns(3)
    with col1:
        selected_strategy = st.selectbox("Strategy", strategy_names)
    with col2:
        start_date = st.date_input("From", value=pd.Timestamp("2023-01-01"))
    with col3:
        end_date = st.date_input("To", value=pd.Timestamp.today())

    if st.button("▶️ Run Backtest"):
        st.info("🚧 Backtest engine — connect src/backtest.py to run full simulation.")
        st.markdown("""
        **Backtest will include:**
        - Interactive equity curve vs Nifty 500 benchmark
        - Bull / bear / sideways regime shading
        - STCG 20% (< 1 yr) and LTCG 12.5% (> 1 yr) tax modelling
        - Trade log: entry/exit dates, P&L, holding days
        - Max drawdown, CAGR, Sharpe ratio, V3 score
        """)

    # Show cached results if they exist
    section("Cached Results")
    results_dir = ROOT / "backtest_results"
    if results_dir.exists():
        summary_files = sorted(results_dir.glob("summary_*.csv"), reverse=True)
        if summary_files:
            for sf in summary_files:
                label = sf.stem.replace("summary_", "Window: ")
                with st.expander(f"📈 {label}", expanded=True):
                    df_sum = pd.read_csv(sf)

                    def style_backtest(df):
                        styles = pd.DataFrame("", index=df.index, columns=df.columns)
                        for col in ["win_rate", "expectancy", "cagr"]:
                            if col in df.columns:
                                styles[col] = df[col].apply(
                                    lambda v: "color:#16A34A;font-weight:700;" if float(v or 0) > 0
                                    else "color:#DC2626;font-weight:700;"
                                )
                        if "max_dd" in df.columns:
                            styles["max_dd"] = df["max_dd"].apply(
                                lambda v: "color:#DC2626;font-weight:600;" if float(v or 0) < -30
                                else "color:#D97706;"
                            )
                        return styles

                    st.dataframe(
                        df_sum.style.apply(style_backtest, axis=None),
                        use_container_width=True, hide_index=True
                    )
        else:
            st.info("No cached backtest results yet. Run `python backtest_all_strategies_final.py` locally.")
    else:
        st.info("No cached backtest results yet. Run `python backtest_all_strategies_final.py` locally.")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 6 — ALERTS & AUTOMATION
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "🔔 Alerts & Automation":
    st.markdown("""
    <div class='page-header'>
      <h1>🔔 Alerts & Automation</h1>
      <div class='page-subtitle'>Email config, run schedule, and GitHub Actions secrets</div>
    </div>
    """, unsafe_allow_html=True)

    section("Email Configuration")
    col1, col2 = st.columns(2)
    with col1:
        st.text_input("Gmail sender",    value=os.environ.get("GMAIL_USER", ""),      disabled=True)
        st.text_input("Recipient email", value=os.environ.get("RECIPIENT_EMAIL", ""), disabled=True)
    with col2:
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        if st.button("📨 Send Test Email"):
            try:
                from src.email_report import send_weekly_report
                result = send_weekly_report(
                    results={"weekly_buy": pd.DataFrame(), "weekly_sell": pd.DataFrame(),
                             "monthly_buy": pd.DataFrame(), "monthly_sell": pd.DataFrame()},
                    universe_summary={"stock_count": 0, "etf_count": 0},
                    portfolio_tickers=set(), removed_tickers=set(),
                    run_date=datetime.today().strftime("%Y-%m-%d"),
                )
                if result:
                    st.success("✅ Test email sent!")
                else:
                    st.error("❌ Email failed — check GMAIL credentials.")
            except Exception as e:
                st.error(f"Error: {e}")

        st.markdown(
            f"<div style='margin-top:12px;'>"
            f"<a href='{DASHBOARD_URL}' target='_blank' "
            f"style='color:#2563EB;font-size:13px;font-weight:600;text-decoration:none;'>"
            f"🔗 Dashboard link included in emails ↗</a></div>",
            unsafe_allow_html=True
        )

    st.divider()
    section("Run Schedule")
    schedule_data = {
        "Workflow":   ["weekly_signals.yml", "weekend_universe_refresh.yml"],
        "Trigger":    ["Every Friday 9:00 PM IST", "Every Saturday 6:00 AM IST"],
        "Action":     ["Fetch Sheet → Signals → Email → Commit",
                       "Fetch Sheet → Commit (dashboard refresh)"],
        "Note":       ["Last Friday of month also runs S1 + S3 monthly strategies",
                       "No signal run — universe refresh only"],
    }
    st.dataframe(pd.DataFrame(schedule_data), use_container_width=True, hide_index=True)

    st.divider()
    section("Required GitHub Secrets")
    secrets_data = {
        "Secret":   ["UPSTOX_API_KEY", "UPSTOX_API_SECRET", "UPSTOX_REDIRECT_URI",
                     "UPSTOX_REFRESH_TOKEN", "UPSTOX_TOKEN", "UPSTOX_TOKEN_EXPIRY",
                     "GMAIL_USER", "GMAIL_PASS", "RECIPIENT_EMAIL",
                     "GOOGLE_SHEETS_CREDENTIALS", "DASHBOARD_URL"],
        "Purpose":  ["Upstox app API key", "Upstox app API secret",
                     "Your app URL (e.g. https://your-app.streamlit.app)",
                     "Set automatically after first OAuth login",
                     "Access token — auto-refreshed daily",
                     "Token expiry timestamp — auto-updated",
                     "Gmail sender address", "Gmail app password",
                     "Email recipient", "Google service account JSON",
                     "Streamlit dashboard URL for email reports"],
        "Required": ["✅ Yes", "✅ Yes", "✅ Yes",
                     "⚡ Auto-set", "⚡ Auto-refreshed", "⚡ Auto-updated",
                     "✅ Yes", "✅ Yes", "✅ Yes",
                     "Optional", "Optional"],
    }
    st.dataframe(pd.DataFrame(secrets_data), use_container_width=True, hide_index=True)

    st.divider()
    section("Manual Trigger")
    st.info("Go to your GitHub repo → Actions → Weekly Signal Run → Run workflow to trigger manually.")

import os  # noqa
