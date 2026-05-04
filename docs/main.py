# main.py
# ─────────────────────────────────────────────────────────────────────────────
# Nifty Options Algo Trader — Main Entry Point
# Run: python main.py --mode paper
# ─────────────────────────────────────────────────────────────────────────────

import sys
import click
from datetime import datetime
from loguru import logger
from pathlib import Path
from rich.console import Console

from config.settings import INDICES, IST, MODE, LOG_DIR
from utils.kite_client import KiteClient
from utils.paper_engine import PaperEngine
from utils.scheduler import BotScheduler, is_trading_day
from strategies.strategy_selector import StrategySelector
from reports.daily_report import generate_daily_report, generate_weekly_report

Path(LOG_DIR).mkdir(exist_ok=True)
console = Console()

# ── Logger setup ──────────────────────────────────────────────────────────────
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="INFO",
    colorize=True,
)
logger.add(
    f"{LOG_DIR}/bot_{{time:YYYY-MM-DD}}.log",
    rotation="1 day",
    retention="14 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
)


class AlgoBot:
    """
    Top-level bot controller.
    Wires together: Kite client → Paper engine → Strategy selector → Scheduler.
    """

    def __init__(self):
        logger.info("🤖 Initializing Algo Bot...")
        self.kite      = KiteClient()
        self.engine    = PaperEngine(self.kite.kite)
        self.selector  = StrategySelector(self.kite.kite, self.engine)

        # Pre-fetch instrument tokens for index spot prices
        self.spot_tokens = {
            idx: cfg["symbol"] for idx, cfg in INDICES.items()
        }

    # ── Called by Scheduler ───────────────────────────────────────────────────

    def pre_market(self):
        """Pre-market preparation: reset day state."""
        logger.info("🌅 Pre-market prep started")
        self.selector.reset_day()
        self.engine.daily_pnl = 0.0
        logger.info("Pre-market prep complete. Ready for 9:15 AM open.")

    def run_cycle(self):
        """
        Main strategy cycle — called every minute during market hours.
        Iterates over all three indices.
        """
        vix = self.kite.get_vix()
        if vix is None:
            logger.warning("Could not fetch VIX — skipping cycle")
            return

        for index, cfg in INDICES.items():
            try:
                spot_data = self.kite.get_ltp([cfg["symbol"]])
                spot_price = spot_data.get(cfg["symbol"])
                if not spot_price:
                    continue

                # Fetch candle data
                # Note: instrument tokens must be set after instruments() call
                # Here we use spot symbol as a placeholder — in production,
                # map to actual NSE:NIFTY 50 token via kite.instruments("NSE")
                token = self._get_index_token(index)
                if token is None:
                    continue

                df_1min = self.kite.get_historical(token, interval="minute",    days_back=1)
                df_5min = self.kite.get_historical(token, interval="5minute",   days_back=1)

                if df_1min is None or df_5min is None:
                    continue

                self.selector.run_cycle(
                    index       = index,
                    spot_price  = spot_price,
                    vix         = vix,
                    df_1min     = df_1min,
                    df_5min     = df_5min,
                )

            except Exception as e:
                logger.exception(f"Error in run_cycle for {index}: {e}")

        # Print status every cycle
        status = self.engine.status()
        logger.info(
            f"💼 Status | Capital=₹{status['capital']:,} "
            f"Available=₹{status['available_capital']:,} "
            f"Open={status['open_positions']} "
            f"DayP&L=₹{status['daily_pnl']:.2f}"
        )

    def monitor(self):
        """Monitor open positions for SL/Target hits."""
        self.engine.monitor_positions()

    def squareoff_all(self):
        """Force exit all positions."""
        self.engine.squareoff_all()

    def daily_report(self):
        """Generate daily report and optionally weekly report."""
        generate_daily_report()

        # Generate weekly report on Fridays
        if datetime.now(IST).weekday() == 4:  # Friday
            generate_weekly_report()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_index_token(self, index: str) -> int | None:
        """
        Return instrument token for index spot.
        Tokens are stable — hardcoded for efficiency.
        Get fresh tokens from: kite.instruments("NSE")
        """
        # These are real NSE instrument tokens (verify via kite.instruments)
        TOKEN_MAP = {
            "NIFTY":     256265,   # NIFTY 50
            "BANKNIFTY": 260105,   # NIFTY BANK
            "FINNIFTY":  257801,   # NIFTY FIN SERVICE
        }
        return TOKEN_MAP.get(index)


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--mode",   default="paper", type=click.Choice(["paper", "live"]),
              help="Trading mode (default: paper)")
@click.option("--report", is_flag=True, help="Generate today's report and exit")
@click.option("--weekly", is_flag=True, help="Generate weekly report and exit")
def main(mode: str, report: bool, weekly: bool):
    """
    🤖 Nifty Options Algo Trader

    Autonomous options buying bot for Nifty, BankNifty, FinNifty.
    Runs in paper mode by default. No human intervention needed.
    """
    if mode == "live":
        console.print("[bold red]⚠️  LIVE MODE: Real orders will be placed![/bold red]")
        if not click.confirm("Are you sure you want to run in LIVE mode?"):
            sys.exit(0)

    console.print(f"[bold cyan]🚀 Starting Algo Bot in {mode.upper()} mode[/bold cyan]")

    bot = AlgoBot()

    if report:
        generate_daily_report()
        sys.exit(0)

    if weekly:
        generate_weekly_report()
        sys.exit(0)

    if not is_trading_day():
        console.print("[yellow]Today is not a trading day. Exiting.[/yellow]")
        sys.exit(0)

    scheduler = BotScheduler(bot)

    try:
        scheduler.start()   # Blocks until Ctrl+C
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot shutdown requested")
        scheduler.stop()
        bot.squareoff_all()
        generate_daily_report()


if __name__ == "__main__":
    main()
