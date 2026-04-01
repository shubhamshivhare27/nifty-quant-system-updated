"""
market_calendar.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NSE market holiday calendar and bar timing utilities.

Key problem solved:
  yfinance weekly bars are labeled by MONDAY but close on FRIDAY.
  When Friday is a market holiday (e.g. Good Friday), the weekly bar
  closes on THURSDAY instead. This causes a 1-day discrepancy between
  yfinance and TradingView if not handled correctly.

Usage:
  from src.market_calendar import get_last_trading_day, is_market_open
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from datetime import date, timedelta

# ── NSE Holidays (add each year as needed) ────────────────────────────────────
# Source: nseindia.com/regulations/trading-holidays
NSE_HOLIDAYS = {
    # 2025
    date(2025, 1, 26),   # Republic Day
    date(2025, 2, 26),   # Mahashivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr (Ramadan Eid)
    date(2025, 4, 10),   # Shri Ram Navami
    date(2025, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Gandhi Jayanti / Dussehra
    date(2025, 10, 20),  # Diwali Laxmi Puja (Muhurat Trading)
    date(2025, 10, 21),  # Diwali Balipratipada
    date(2025, 11, 5),   # Prakash Gurpurab
    date(2025, 12, 25),  # Christmas

    # 2026
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 3),    # Holi (Dhulandi)
    date(2026, 3, 30),   # Good Friday
    date(2026, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti / Ram Navami
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 8, 15),   # Independence Day
    date(2026, 9, 17),   # Ganesh Chaturthi
    date(2026, 10, 2),   # Gandhi Jayanti
    date(2026, 12, 25),  # Christmas

    # 2024 (for historical reference)
    date(2024, 1, 22),   # Ayodhya Ram Mandir
    date(2024, 1, 26),   # Republic Day
    date(2024, 3, 25),   # Holi
    date(2024, 3, 29),   # Good Friday
    date(2024, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2024, 4, 17),   # Ram Navami
    date(2024, 5, 1),    # Maharashtra Day
    date(2024, 5, 23),   # Buddha Purnima
    date(2024, 6, 17),   # Bakri Eid
    date(2024, 8, 15),   # Independence Day
    date(2024, 10, 2),   # Gandhi Jayanti / Dussehra
    date(2024, 11, 1),   # Diwali Laxmi Puja
    date(2024, 11, 15),  # Gurunanak Jayanti
    date(2024, 12, 25),  # Christmas
}

# ── Good Friday 2025 specifically ─────────────────────────────────────────────
# March 28, 2025 was Good Friday — NSE was CLOSED
# Weekly bar for week of March 24 closed on THURSDAY March 27
GOOD_FRIDAY_2025 = date(2025, 3, 28)


def is_market_open(d: date) -> bool:
    """Returns True if NSE is open on the given date."""
    # Saturday or Sunday — closed
    if d.weekday() >= 5:
        return False
    # Known NSE holiday — closed
    if d in NSE_HOLIDAYS:
        return False
    return True


def get_last_trading_day_of_week(week_monday: date) -> date:
    """
    Given the Monday of a week, returns the last trading day of that week.
    Normally Friday, but could be Thursday or earlier if Friday is a holiday.
    """
    # Start from Friday (Monday + 4 days) and go backwards
    for days_back in range(5):  # Fri, Thu, Wed, Tue, Mon
        candidate = week_monday + timedelta(days=4 - days_back)
        if is_market_open(candidate):
            return candidate
    # Fallback — return Monday if entire week is holiday (extremely rare)
    return week_monday


def get_week_close_date(yfinance_bar_date) -> date:
    """
    Given a yfinance weekly bar date (Monday label),
    returns the actual date the weekly candle CLOSED on.

    This is important for holiday weeks like Good Friday where
    the market closes on Thursday instead of Friday.

    Args:
        yfinance_bar_date: date or datetime of the Monday-labeled bar

    Returns:
        date: the actual closing date of that weekly candle
    """
    if hasattr(yfinance_bar_date, 'date'):
        yfinance_bar_date = yfinance_bar_date.date()
    elif hasattr(yfinance_bar_date, 'to_pydatetime'):
        yfinance_bar_date = yfinance_bar_date.to_pydatetime().date()

    # Ensure it's actually a Monday (or close to it)
    # yfinance sometimes labels by actual first trading day of week
    # Find the Monday of this bar's week
    days_since_monday = yfinance_bar_date.weekday()  # 0=Mon
    monday = yfinance_bar_date - timedelta(days=days_since_monday)

    return get_last_trading_day_of_week(monday)


def is_safe_to_run_weekly_signals() -> bool:
    """
    Returns True if it is safe to run the weekly signal engine
    (i.e. the current weekly candle is fully closed).

    Safe:  Friday after 3:30 PM IST, Saturday, Sunday
    Unsafe: Monday–Thursday (bar still forming),
            Friday before 3:30 PM IST (bar still forming)
    For holiday Fridays: safe from Thursday 3:30 PM IST onwards
    """
    from datetime import datetime, timezone, timedelta as td

    # Current time in IST (UTC+5:30)
    ist_offset = td(hours=5, minutes=30)
    now_ist = datetime.now(timezone.utc) + ist_offset
    today   = now_ist.date()
    weekday = today.weekday()   # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    hour_ist = now_ist.hour
    minute_ist = now_ist.minute

    # Saturday or Sunday — always safe
    if weekday >= 5:
        return True

    # Friday — safe after 3:30 PM IST
    if weekday == 4:
        if not is_market_open(today):
            # Holiday Friday (e.g. Good Friday) — check Thursday
            # Thursday should have closed — safe any time today
            return True
        # Normal Friday — safe after 3:30 PM IST
        return (hour_ist > 15) or (hour_ist == 15 and minute_ist >= 30)

    # Thursday — check if Friday is a holiday
    if weekday == 3:
        friday = today + timedelta(days=1)
        if not is_market_open(friday):
            # Friday is a holiday — Thursday IS the last trading day
            # Safe after Thursday 3:30 PM IST
            return (hour_ist > 15) or (hour_ist == 15 and minute_ist >= 30)

    # Monday–Wednesday, or Thursday when Friday is normal — not safe
    return False


if __name__ == "__main__":
    # Quick test
    from datetime import date

    test_dates = [
        date(2025, 3, 24),   # Week of March 24 — Good Friday week
        date(2025, 3, 31),   # Week of March 31 — normal week
        date(2026, 3, 30),   # Good Friday 2026
        date(2024, 3, 25),   # Week with Good Friday 2024
    ]

    print("Weekly bar close date test:")
    print(f"{'Bar Label (Monday)':25} {'Actual Close Day':20} {'Close Date'}")
    print("-" * 65)
    for d in test_dates:
        close_date = get_week_close_date(d)
        day_name = close_date.strftime("%A")
        marker = " ← HOLIDAY WEEK" if close_date.weekday() != 4 else ""
        print(f"{str(d):25} {day_name:20} {close_date}{marker}")

    print(f"\nSafe to run weekly signals now: {is_safe_to_run_weekly_signals()}")
