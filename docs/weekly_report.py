# reports/weekly_report.py
# ─────────────────────────────────────────────────────────────────────────────
# Weekly Report — standalone module
# Aggregates all daily logs for the current week and produces:
#   - JSON summary
#   - Rich console table
#   - Per-day P&L breakdown
#   - Cumulative tax paid for the week
# ─────────────────────────────────────────────────────────────────────────────

from reports.daily_report import generate_weekly_report

# This module re-exports generate_weekly_report for clean imports.
# Call directly:
#   from reports.weekly_report import run
#   run()

def run():
    """Generate and print the weekly P&L report."""
    return generate_weekly_report()


if __name__ == "__main__":
    run()
