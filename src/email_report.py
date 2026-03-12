"""
email_report.py
---------------
Sends the weekly/monthly signal email report via Gmail SMTP.

Subject: 📊 Nifty 500 Signals — {date} | {n_buy} BUY | {n_sell} SELL

Sections:
  1. Summary
  2. ⚠️ URGENT: Holdings removed from sheet but still in Upstox
  3. Universe changes (added/removed/TA status changed)
  4. BUY signals table
  5. SELL signals table
  6. Portfolio snapshot
  7. Next signal date
"""

import os
import logging
import smtplib
import pandas as pd
from datetime import datetime, timedelta
from email.mime.text   import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

log = logging.getLogger("email_report")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Dashboard URL — update this if the Streamlit URL changes
DASHBOARD_URL = os.environ.get(
    "DASHBOARD_URL",
    "https://nifty-quant-system-updated-afqpypkjc7xdpnefsq8d3i.streamlit.app"
)


# ─────────────────────────────────────────────────────────────────────────────
# HTML helpers
# ─────────────────────────────────────────────────────────────────────────────

def _df_to_html_table(df: pd.DataFrame, highlight_col: str | None = None) -> str:
    if df.empty:
        return "<p style='color:#888'>No signals.</p>"

    header_style = "background:#1a1a2e;color:#e0e0e0;padding:8px 12px;text-align:left;font-size:12px;"
    cell_style   = "padding:7px 12px;border-bottom:1px solid #2a2a3e;font-size:12px;color:#cccccc;"
    row_style    = "background:#0f0f1a;"
    row_alt      = "background:#13131f;"

    html = "<table style='border-collapse:collapse;width:100%;font-family:monospace;'>"
    html += "<tr>" + "".join(f"<th style='{header_style}'>{c}</th>" for c in df.columns) + "</tr>"

    for i, row in df.iterrows():
        bg = row_style if i % 2 == 0 else row_alt
        html += f"<tr style='{bg}'>"
        for col, val in row.items():
            cell = cell_style
            if col == "signal_type":
                color = "#00e676" if val == "BUY" else "#ff5252"
                cell += f"color:{color};font-weight:bold;"
            html += f"<td style='{cell}'>{val}</td>"
        html += "</tr>"

    html += "</table>"
    return html


def _changes_html(changes_df: pd.DataFrame) -> str:
    if changes_df.empty:
        return "<p style='color:#888'>No changes since last run.</p>"

    html = ""
    for _, row in changes_df.iterrows():
        ct = row.get("change_type", "")
        ticker  = row.get("ticker", "")
        company = row.get("company", "")
        detail  = row.get("detail", "")

        if ct == "ADDED":
            color, icon = "#00e676", "+"
        elif ct == "REMOVED":
            color, icon = "#ff5252", "−"
        else:
            color, icon = "#ffd740", "~"

        html += (
            f"<div style='margin:4px 0;'>"
            f"<span style='color:{color};font-weight:bold;font-family:monospace;'>[{icon}] {ticker}</span>"
            f" <span style='color:#aaa;font-size:12px;'>{company} — {detail}</span>"
            f"</div>"
        )
    return html


# ─────────────────────────────────────────────────────────────────────────────
# Build HTML email body
# ─────────────────────────────────────────────────────────────────────────────

def build_html_body(
    results:           dict,
    universe_summary:  dict,
    portfolio_tickers: set,
    removed_tickers:   set,
    run_date:          str,
) -> str:

    n_buy  = len(results.get("weekly_buy",  pd.DataFrame())) + len(results.get("monthly_buy",  pd.DataFrame()))
    n_sell = len(results.get("weekly_sell", pd.DataFrame())) + len(results.get("monthly_sell", pd.DataFrame()))
    n_stocks = universe_summary.get("stock_count", 0)
    n_etfs   = universe_summary.get("etf_count",   0)

    # Universe changes
    changes_df = pd.DataFrame()
    changes_path = DATA_DIR / "universe_changes.csv"
    if changes_path.exists():
        try:
            all_changes = pd.read_csv(changes_path)
            changes_df  = all_changes[all_changes["run_at"].str.startswith(run_date)] if not all_changes.empty else pd.DataFrame()
        except Exception:
            pass

    # Next signal date (next Friday)
    today = datetime.strptime(run_date, "%Y-%m-%d")
    days_to_friday = (4 - today.weekday()) % 7 or 7
    next_friday = (today + timedelta(days=days_to_friday)).strftime("%d %b %Y")

    # BUY/SELL signal tables
    all_buys  = pd.concat([results.get("weekly_buy",  pd.DataFrame()),
                           results.get("monthly_buy",  pd.DataFrame())], ignore_index=True)
    all_sells = pd.concat([results.get("weekly_sell", pd.DataFrame()),
                           results.get("monthly_sell", pd.DataFrame())], ignore_index=True)

    buy_cols  = ["ticker", "strategy_name", "signal_type", "date",
                 "RSI14_daily", "RSI14_weekly", "RSI14_monthly",
                 "MACD_line_weekly", "MACD_signal_weekly",
                 "SSF50_weekly", "triggered_conditions"]
    sell_cols = ["ticker", "strategy_name", "signal_type", "date", "triggered_conditions"]

    buy_table  = _df_to_html_table(
        all_buys[[c for c in buy_cols if c in all_buys.columns]].head(50)
    ) if not all_buys.empty else "<p style='color:#888'>No BUY signals.</p>"

    sell_table = _df_to_html_table(
        all_sells[[c for c in sell_cols if c in all_sells.columns]].head(50)
    ) if not all_sells.empty else "<p style='color:#888'>No SELL signals.</p>"

    section_style = "background:#13131f;border-radius:8px;padding:20px;margin-bottom:20px;"
    h2_style      = "color:#7c83fd;margin:0 0 14px 0;font-size:15px;letter-spacing:0.5px;"

    removed_html = ""
    if removed_tickers:
        removed_html = f"""
        <div style='{section_style}border-left:4px solid #ff5252;'>
          <h2 style='color:#ff5252;margin:0 0 12px 0;'>⚠️ URGENT — Holdings Removed from Master Sheet</h2>
          <p style='color:#ffb3b3;font-size:13px;'>
            The following stocks are <strong>still held in your Upstox portfolio</strong>
            but have been removed from the Google Sheet master list.
            Exit signals are still being monitored automatically.
          </p>
          {''.join(f'<div style="color:#ff5252;font-family:monospace;margin:4px 0;">⚠️ {t}</div>' for t in sorted(removed_tickers))}
        </div>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"></head>
    <body style="background:#0a0a14;color:#e0e0e0;font-family:Arial,sans-serif;padding:24px;max-width:900px;margin:auto;">

      <div style="background:linear-gradient(135deg,#1a1a3e,#0f0f28);border-radius:12px;padding:24px;margin-bottom:24px;">
        <h1 style="color:#7c83fd;margin:0 0 8px 0;font-size:22px;">📊 Nifty 500 Signal Engine</h1>
        <p style="color:#aaa;margin:0 0 12px 0;font-size:13px;">Signal Date: {run_date}</p>
        <a href="{DASHBOARD_URL}"
           style="display:inline-block;background:#7c83fd;color:#fff;text-decoration:none;
                  padding:8px 20px;border-radius:6px;font-size:13px;font-weight:bold;">
          🔗 View Live Dashboard
        </a>
      </div>

      <!-- Summary -->
      <div style='{section_style}'>
        <h2 style='{h2_style}'>📋 Summary</h2>
        <table style='width:100%;'>
          <tr>
            <td style='color:#aaa;font-size:13px;'>BUY Signals</td>
            <td style='color:#00e676;font-size:20px;font-weight:bold;'>{n_buy}</td>
            <td style='color:#aaa;font-size:13px;'>SELL Signals</td>
            <td style='color:#ff5252;font-size:20px;font-weight:bold;'>{n_sell}</td>
          </tr>
          <tr>
            <td style='color:#aaa;font-size:13px;'>Stocks in Universe</td>
            <td style='color:#e0e0e0;font-size:16px;'>{n_stocks}</td>
            <td style='color:#aaa;font-size:13px;'>ETFs in Universe</td>
            <td style='color:#e0e0e0;font-size:16px;'>{n_etfs}</td>
          </tr>
          <tr>
            <td style='color:#aaa;font-size:13px;'>Strategies Run</td>
            <td colspan='3' style='color:#e0e0e0;font-size:13px;'>
              S2 Weekly EMA Pullback | S4 Weekly SSF50 Breakout | S5 ETF Weekly
              {"| S1 Monthly EMA20 | S3 Monthly SSF50" if results.get("monthly_buy") is not None else ""}
            </td>
          </tr>
        </table>
      </div>

      {removed_html}

      <!-- Universe Changes -->
      <div style='{section_style}'>
        <h2 style='{h2_style}'>🔄 Universe Changes Since Last Run</h2>
        {_changes_html(changes_df)}
      </div>

      <!-- BUY Signals -->
      <div style='{section_style}'>
        <h2 style='color:#00e676;margin:0 0 14px 0;font-size:15px;'>📈 BUY Signals ({n_buy})</h2>
        {buy_table}
      </div>

      <!-- SELL Signals -->
      <div style='{section_style}'>
        <h2 style='color:#ff5252;margin:0 0 14px 0;font-size:15px;'>📉 SELL Signals ({n_sell})</h2>
        {sell_table}
      </div>

      <!-- Footer -->
      <div style='text-align:center;padding:16px;color:#555;font-size:12px;'>
        Next signal run: <strong style='color:#7c83fd;'>{next_friday}</strong>
        &nbsp;|&nbsp;
        <a href="{DASHBOARD_URL}" style="color:#7c83fd;text-decoration:none;">
          Live Dashboard ↗
        </a>
        &nbsp;|&nbsp; Nifty 500 Quant Signal Engine
      </div>

    </body>
    </html>
    """
    return html


# ─────────────────────────────────────────────────────────────────────────────
# Send email
# ─────────────────────────────────────────────────────────────────────────────

def send_weekly_report(
    results:           dict,
    universe_summary:  dict,
    portfolio_tickers: set,
    removed_tickers:   set,
    run_date:          str,
) -> bool:

    gmail_user  = os.environ.get("GMAIL_USER", "")
    gmail_pass  = os.environ.get("GMAIL_PASS", "")
    recipient   = os.environ.get("RECIPIENT_EMAIL", gmail_user)

    if not gmail_user or not gmail_pass:
        log.warning("GMAIL_USER / GMAIL_PASS not set — skipping email.")
        return False

    n_buy  = len(results.get("weekly_buy",  pd.DataFrame())) + len(results.get("monthly_buy",  pd.DataFrame()))
    n_sell = len(results.get("weekly_sell", pd.DataFrame())) + len(results.get("monthly_sell", pd.DataFrame()))

    subject = f"📊 Nifty 500 Signals — {run_date} | {n_buy} BUY | {n_sell} SELL"

    html_body = build_html_body(
        results, universe_summary, portfolio_tickers, removed_tickers, run_date
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = gmail_user
    msg["To"]      = recipient
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, recipient, msg.as_string())
        log.info(f"Email sent to {recipient}: '{subject}'")
        return True
    except Exception as e:
        log.error(f"Email send failed: {e}", exc_info=True)
        return False
