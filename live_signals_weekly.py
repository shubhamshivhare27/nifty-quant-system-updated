"""
live_signals_weekly.py
-----------------------
Friday 9pm IST orchestrator — runs the full weekly signal pipeline:

  1. Fetch Google Sheet → update stock_universe.csv + etf_universe.csv
  2. Detect universe changes vs previous run
  3. Sync Upstox portfolio holdings
  4. Run S2, S4 (weekly stock strategies) + S5 (ETF strategy)
  5. On last Friday of month: also run S1, S3 (monthly strategies)
  6. Send email report
  7. Commit updated CSVs (done by GitHub Actions after this script exits)
"""

import sys
import logging
import calendar
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("live_signals_weekly")

# Add src/ to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.universe_loader import run as refresh_universe
from src.signal_engine   import SignalEngine

try:
    from src.portfolio   import get_portfolio_tickers, get_removed_tickers
except ImportError:
    log.warning("portfolio.py not available — proceeding without Upstox holdings.")
    def get_portfolio_tickers(): return set()
    def get_removed_tickers(sheet_tickers): return set()

try:
    from src.email_report import send_weekly_report
except ImportError:
    log.warning("email_report.py not available — email will not be sent.")
    def send_weekly_report(*args, **kwargs): pass


def is_last_friday_of_month(dt: datetime) -> bool:
    """Returns True if dt is the last Friday of its month."""
    if dt.weekday() != 4:   # 4 = Friday
        return False
    next_friday = dt.day + 7
    return next_friday > calendar.monthrange(dt.year, dt.month)[1]


def main():
    today = datetime.today()
    run_date = today.strftime("%Y-%m-%d")
    log.info(f"═══ Weekly Signal Run — {run_date} ═══")

    # ── Step 1: Refresh universe ──────────────────────────────────────────────
    log.info("Step 1: Refreshing universe from Google Sheet ...")
    universe_summary = refresh_universe()
    stock_tickers = universe_summary["stock_tickers"]
    etf_tickers   = universe_summary["etf_tickers"]
    log.info(f"  Stocks: {universe_summary['stock_count']}  |  ETFs: {universe_summary['etf_count']}")

    # ── Step 2: Sync Upstox portfolio ────────────────────────────────────────
    log.info("Step 2: Syncing Upstox portfolio ...")
    portfolio_tickers  = get_portfolio_tickers()
    removed_from_sheet = get_removed_tickers(set(stock_tickers))
    if removed_from_sheet:
        log.warning(f"⚠️  Holdings removed from sheet: {removed_from_sheet}")

    # ── Step 3: Determine run mode ────────────────────────────────────────────
    if is_last_friday_of_month(today):
        mode = "both"
        log.info("Step 3: Last Friday of month — running WEEKLY + MONTHLY strategies.")
    else:
        mode = "weekly"
        log.info("Step 3: Running WEEKLY strategies only.")

    # ── Step 4: Run signal engine ─────────────────────────────────────────────
    log.info("Step 4: Running signal engine ...")
    engine = SignalEngine(run_date=run_date, mode=mode)
    results = engine.run_all(
        stock_tickers      = stock_tickers,
        etf_tickers        = etf_tickers,
        portfolio_tickers  = portfolio_tickers,
        removed_from_sheet = removed_from_sheet,
    )

    log.info(f"  Weekly  BUY:  {len(results['weekly_buy'])}")
    log.info(f"  Weekly  SELL: {len(results['weekly_sell'])}")
    log.info(f"  Monthly BUY:  {len(results['monthly_buy'])}")
    log.info(f"  Monthly SELL: {len(results['monthly_sell'])}")

    # ── Step 5: Send email report ─────────────────────────────────────────────
    log.info("Step 5: Sending email report ...")
    send_weekly_report(
        results           = results,
        universe_summary  = universe_summary,
        portfolio_tickers = portfolio_tickers,
        removed_tickers   = removed_from_sheet,
        run_date          = run_date,
    )

    log.info("═══ Weekly Signal Run Complete ═══")
    return results


if __name__ == "__main__":
    main()
