# main.py
# ─────────────────────────────────────────────────────────────────────────────
# Nifty Options Algo Trader — Main Entry Point
#
# Usage:
#   python main.py                  # paper trade (default)
#   python main.py --mode paper     # explicit paper mode
#   python main.py --report         # print today's report and exit
#   python main.py --weekly         # print weekly report and exit
#   python main.py --backtest       # run backtest on historical data
# ─────────────────────────────────────────────────────────────────────────────

import sys
import click
from datetime import datetime
from pathlib import Path
from rich.console import Console

from config.settings import INDICES, IST, LOG_DIR
from config.logging_config import setup_logging
from utils.kite_client import KiteClient
from utils.paper_engine import PaperEngine
from utils.risk_manager import RiskManager
from utils.scheduler import BotScheduler, is_trading_day
from strategies.strategy_selector import StrategySelector
from reports.daily_report import generate_daily_report, generate_weekly_report

from loguru import logger

Path(LOG_DIR).mkdir(exist_ok=True)
setup_logging()
console = Console()

# Instrument tokens for NSE index spot prices (stable — verify via kite.instruments("NSE"))
INDEX_TOKENS = {
    "NIFTY":     256265,
    "BANKNIFTY": 260105,
    "FINNIFTY":  257801,
}


class AlgoBot:
    """
    Top-level autonomous bot controller.
    Wires: KiteClient → PaperEngine → RiskManager → StrategySelector → Scheduler.
    """

    def __init__(self):
        logger.info("═" * 60)
        logger.info("🤖  NIFTY OPTIONS ALGO TRADER  (PAPER MODE)")
        logger.info("═" * 60)

        self.kite     = KiteClient()
        self.engine   = PaperEngine(self.kite)
        self.risk     = RiskManager(self.engine)
        self.selector = StrategySelector(self.kite, self.engine, self.risk)
        self._cycle_count = 0

    # ── Scheduler-called methods ──────────────────────────────────────────────

    def pre_market(self):
        """Reset all daily state before 9:15 open."""
        logger.info("🌅 Pre-market reset")
        self.selector.reset_day()
        self.engine.reset_day()
        self.risk.log_risk_status()

    def run_cycle(self):
        """Main strategy cycle — called every minute by scheduler."""
        self._cycle_count += 1

        # Connectivity check every 10 cycles
        if self._cycle_count % 10 == 0:
            if not self._health_check():
                return

        vix = self.kite.get_vix()
        if vix is None:
            logger.warning("VIX unavailable — skipping cycle")
            return

        for index in INDICES:
            try:
                self._process_index(index, vix)
            except Exception as e:
                logger.exception(f"Error processing {index}: {e}")

        # Status every cycle
        s = self.engine.status()
        logger.info(
            f"💼 Capital=₹{s['available_capital']:,.0f} | "
            f"Open={s['open_positions']} | "
            f"DayP&L=₹{s['daily_pnl']:+.2f} | "
            f"Trades={s['total_trades']}"
        )

    def monitor(self):
        """Check SL/Target for all open positions."""
        self.engine.monitor_positions()
        if self._cycle_count % 5 == 0:
            self.risk.log_risk_status()

    def squareoff_all(self):
        """Force-close all open positions (EOD)."""
        logger.info("🔔 EOD square-off")
        self.engine.squareoff_all()

    def daily_report(self):
        """Generate and save daily P&L report."""
        generate_daily_report()
        if datetime.now(IST).weekday() == 4:  # Friday
            generate_weekly_report()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _process_index(self, index: str, vix: float):
        """Fetch data and run strategy cycle for one index."""
        cfg         = INDICES[index]
        spot_data   = self.kite.get_ltp([cfg["symbol"]])
        spot_price  = spot_data.get(cfg["symbol"])
        if not spot_price:
            logger.debug(f"{index}: spot LTP unavailable")
            return

        token = INDEX_TOKENS.get(index)
        if token is None:
            return

        df_1min = self.kite.get_historical(token, interval="minute",  days_back=1)
        df_5min = self.kite.get_historical(token, interval="5minute", days_back=1)

        if df_1min is None or df_5min is None or len(df_1min) < 15:
            logger.debug(f"{index}: insufficient candle data")
            return

        self.selector.run_cycle(
            index      = index,
            spot_price = spot_price,
            vix        = vix,
            df_1min    = df_1min,
            df_5min    = df_5min,
        )

    def _health_check(self) -> bool:
        """Verify API connectivity. Returns True if healthy."""
        try:
            result = self.kite.get_ltp(["NSE:NIFTY 50"])
            if result:
                return True
            logger.warning("Health check: empty LTP response")
            return False
        except Exception as e:
            logger.error(f"Health check FAILED: {e}")
            return False


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--mode",      default="paper",
              type=click.Choice(["paper", "live"]),
              help="Trading mode. Default: paper (safe)")
@click.option("--report",    is_flag=True, help="Print today's P&L report and exit")
@click.option("--weekly",    is_flag=True, help="Print weekly P&L report and exit")
@click.option("--backtest",  is_flag=True, help="Run backtest simulation and exit")
def main(mode: str, report: bool, weekly: bool, backtest: bool):
    """
    🤖  Nifty Options Algo Trader

    \b
    Autonomous paper-trading bot for Nifty, BankNifty, FinNifty weekly options.
    Runs fully hands-free 9:15 AM – 3:15 PM IST on trading days.
    All P&L reported after STT, brokerage, GST, stamp duty deduction.
    """
    if mode == "live":
        console.print("\n[bold red]⚠️  WARNING: LIVE MODE — Real orders will be placed![/bold red]")
        console.print("[red]This is NOT paper trading. Real money is at risk.[/red]\n")
        if not click.confirm("Type 'yes' to confirm LIVE mode"):
            console.print("Aborted.")
            sys.exit(0)

    # Standalone report commands
    if report:
        generate_daily_report()
        sys.exit(0)

    if weekly:
        generate_weekly_report()
        sys.exit(0)

    if backtest:
        from utils.backtester import run_backtest
        run_backtest()
        sys.exit(0)

    if not is_trading_day():
        console.print("[yellow]⚠️  Today is not a trading day (weekend/holiday). Exiting.[/yellow]")
        sys.exit(0)

    console.print(f"\n[bold cyan]🚀 Starting in {mode.upper()} mode[/bold cyan]")
    bot = AlgoBot()

    scheduler = BotScheduler(bot)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown requested by user")
    finally:
        scheduler.stop()
        bot.squareoff_all()
        generate_daily_report()
        console.print("\n[bold green]✅ Bot shut down cleanly.[/bold green]")


if __name__ == "__main__":
    main()
