# utils/scheduler.py
# ─────────────────────────────────────────────────────────────────────────────
# Market Hours Scheduler
# Controls when the bot runs, which indices to process, and
# triggers the end-of-day square-off automatically.
# Uses APScheduler for reliable job scheduling.
# ─────────────────────────────────────────────────────────────────────────────

from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from config.settings import IST, SQUAREOFF_TIME, INDICES


# Indian market holidays FY 2024-25 (NSE official list)
# Update annually
MARKET_HOLIDAYS_2025 = {
    "2025-01-26",  # Republic Day
    "2025-02-26",  # Mahashivratri
    "2025-03-14",  # Holi
    "2025-04-10",  # Good Friday (tentative)
    "2025-04-14",  # Dr. Ambedkar Jayanti
    "2025-04-18",  # Good Friday
    "2025-05-01",  # Maharashtra Day
    "2025-08-15",  # Independence Day
    "2025-08-27",  # Ganesh Chaturthi
    "2025-10-02",  # Gandhi Jayanti
    "2025-10-20",  # Diwali Laxmi Pujan (tentative)
    "2025-10-21",  # Diwali Balipratipada
    "2025-11-05",  # Prakash Gurpurb
    "2025-12-25",  # Christmas
}


def is_trading_day() -> bool:
    """Check if today is a valid NSE trading day."""
    now     = datetime.now(IST)
    weekday = now.weekday()   # 0=Mon, 6=Sun

    # Weekend
    if weekday >= 5:
        return False

    # Holiday
    date_str = now.strftime("%Y-%m-%d")
    if date_str in MARKET_HOLIDAYS_2025:
        logger.info(f"📅 Today ({date_str}) is a market holiday. Bot will not run.")
        return False

    return True


def is_market_hours() -> bool:
    """Check if current time is within NSE trading hours."""
    now  = datetime.now(IST).time()
    open_  = dtime(9, 15)
    close_ = dtime(15, 30)
    return open_ <= now <= close_


class BotScheduler:
    """
    Manages all scheduled jobs for the trading bot.

    Jobs:
    - Every 1 minute  (9:15–15:15): Main strategy cycle
    - Every 1 minute  (9:15–15:15): Monitor open positions (SL/Target)
    - At 15:15        : Force square-off all open positions
    - At 15:30        : Generate daily report
    - At 9:00         : Pre-market prep (token refresh check)
    """

    def __init__(self, bot_runner):
        """
        Args:
            bot_runner: Object with methods:
                        .run_cycle()      — main strategy loop
                        .monitor()        — check SL/Target
                        .squareoff_all()  — end-of-day exit
                        .daily_report()   — generate report
                        .pre_market()     — pre-open prep
        """
        self.runner    = bot_runner
        self.scheduler = BlockingScheduler(timezone=IST)
        self._add_jobs()

    def _add_jobs(self):
        # Pre-market prep at 9:00 AM
        self.scheduler.add_job(
            self._pre_market_job,
            CronTrigger(hour=9, minute=0, timezone=IST),
            id="pre_market",
            name="Pre-market prep",
        )

        # Main strategy cycle: every 1 minute, 9:15–15:15
        self.scheduler.add_job(
            self._strategy_job,
            CronTrigger(
                hour="9-15", minute="*",
                second=5,                   # 5s after candle close
                timezone=IST,
            ),
            id="strategy_cycle",
            name="Strategy cycle",
        )

        # Position monitor: every 1 minute, 9:15–15:25
        self.scheduler.add_job(
            self._monitor_job,
            CronTrigger(hour="9-15", minute="*", second=30, timezone=IST),
            id="monitor_positions",
            name="Position monitor",
        )

        # End-of-day square-off at 15:15
        sq_h, sq_m = SQUAREOFF_TIME
        self.scheduler.add_job(
            self._squareoff_job,
            CronTrigger(hour=sq_h, minute=sq_m, timezone=IST),
            id="eod_squareoff",
            name="EOD Square-off",
        )

        # Daily report at 15:30
        self.scheduler.add_job(
            self._report_job,
            CronTrigger(hour=15, minute=30, timezone=IST),
            id="daily_report",
            name="Daily P&L report",
        )

        logger.info("📅 All scheduled jobs registered")

    # ── Job Handlers ──────────────────────────────────────────────────────────

    def _pre_market_job(self):
        if not is_trading_day():
            return
        logger.info("⏰ Pre-market job running")
        try:
            self.runner.pre_market()
        except Exception as e:
            logger.error(f"Pre-market job error: {e}")

    def _strategy_job(self):
        if not is_trading_day() or not is_market_hours():
            return
        now = datetime.now(IST).time()
        # Don't fire new entries after 3:00 PM
        if now >= dtime(15, 0):
            return
        try:
            self.runner.run_cycle()
        except Exception as e:
            logger.exception(f"Strategy cycle error: {e}")

    def _monitor_job(self):
        if not is_trading_day():
            return
        try:
            self.runner.monitor()
        except Exception as e:
            logger.error(f"Monitor job error: {e}")

    def _squareoff_job(self):
        if not is_trading_day():
            return
        logger.info("🔔 EOD square-off triggered")
        try:
            self.runner.squareoff_all()
        except Exception as e:
            logger.error(f"Square-off job error: {e}")

    def _report_job(self):
        if not is_trading_day():
            return
        logger.info("📊 Generating daily report")
        try:
            self.runner.daily_report()
        except Exception as e:
            logger.error(f"Daily report job error: {e}")

    def start(self):
        logger.info("🚀 Scheduler started. Bot is running autonomously.")
        self.scheduler.start()

    def stop(self):
        self.scheduler.shutdown(wait=False)
        logger.info("⛔ Scheduler stopped.")
