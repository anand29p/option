# utils/scheduler.py
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from config.settings import IST, SQUAREOFF_TIME

MARKET_HOLIDAYS_2025 = {
    "2025-01-26", "2025-02-26", "2025-03-14", "2025-04-10",
    "2025-04-14", "2025-04-18", "2025-05-01", "2025-08-15",
    "2025-08-27", "2025-10-02", "2025-10-20", "2025-10-21",
    "2025-11-05", "2025-12-25",
}


def is_trading_day() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    date_str = now.strftime("%Y-%m-%d")
    if date_str in MARKET_HOLIDAYS_2025:
        logger.info(f"📅 Today ({date_str}) is a market holiday.")
        return False
    return True


def is_market_hours() -> bool:
    now = datetime.now(IST).time()
    return dtime(9, 15) <= now <= dtime(15, 30)


class BotScheduler:
    def __init__(self, bot_runner):
        self.runner = bot_runner
        self.scheduler = BlockingScheduler(timezone=IST)
        self._add_jobs()

    def _add_jobs(self):
        self.scheduler.add_job(
            self._pre_market_job,
            CronTrigger(hour=9, minute=0, timezone=IST),
            id="pre_market", name="Pre-market prep",
        )
        self.scheduler.add_job(
            self._strategy_job,
            CronTrigger(hour="9-15", minute="*", second=5, timezone=IST),
            id="strategy_cycle", name="Strategy cycle",
        )
        self.scheduler.add_job(
            self._monitor_job,
            CronTrigger(hour="9-15", minute="*", second=30, timezone=IST),
            id="monitor_positions", name="Position monitor",
        )
        sq_h, sq_m = SQUAREOFF_TIME
        self.scheduler.add_job(
            self._squareoff_job,
            CronTrigger(hour=sq_h, minute=sq_m, timezone=IST),
            id="eod_squareoff", name="EOD Square-off",
        )
        self.scheduler.add_job(
            self._report_job,
            CronTrigger(hour=15, minute=30, timezone=IST),
            id="daily_report", name="Daily P&L report",
        )
        logger.info("📅 All scheduled jobs registered")

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
        if datetime.now(IST).time() >= dtime(15, 0):
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
