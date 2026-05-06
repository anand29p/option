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
#   python main.py --dashboard      # start web dashboard only
# ─────────────────────────────────────────────────────────────────────────────

import sys
import threading
import click
from datetime import datetime
from pathlib import Path
from rich.console import Console

from config.settings import INDICES, IST, LOG_DIR, INDEX_SECURITY_IDS
from config.logging_config import setup_logging
from utils.dhan_client import DhanClient
from utils.paper_engine import PaperEngine
from utils.risk_manager import RiskManager
from utils.scheduler import BotScheduler, is_trading_day
from strategies.strategy_selector import StrategySelector
from reports.daily_report import generate_daily_report, generate_weekly_report
from utils.global_context import get_global_context
from utils.news_sentiment import get_news_sentiment
from utils.market_data_recorder import MarketDataRecorder
from utils.option_chain import get_nearest_weekly_expiry

from loguru import logger

Path(LOG_DIR).mkdir(exist_ok=True)
setup_logging()
console = Console()


class AlgoBot:
    """
    Top-level autonomous bot controller.
    Wires: DhanClient → PaperEngine → RiskManager → StrategySelector → Scheduler.
    """

    def __init__(self):
        logger.info("═" * 60)
        logger.info("🤖  NIFTY OPTIONS ALGO TRADER  (PAPER MODE) — Dhan API")
        logger.info("═" * 60)

        self.dhan     = DhanClient()
        self.engine   = PaperEngine(self.dhan)
        self.risk     = RiskManager(self.engine)
        self.selector = StrategySelector(self.dhan, self.engine, self.risk)
        self.recorder = MarketDataRecorder()
        self._cycle_count = 0

    # ── Scheduler-called methods ──────────────────────────────────────────────

    def pre_market(self):
        """Reset all daily state and log global context before 9:15 open."""
        logger.info("🌅 Pre-market reset")
        self.selector.reset_day()
        self.engine.reset_day()
        self.risk.log_risk_status()

        # Log global market context at open
        ctx = get_global_context(force=True)
        logger.info(
            f"🌍 Global: US={ctx.us_bias} Asia={ctx.asia_bias} "
            f"GIFT Nifty={ctx.gift_nifty_chg:+.2f}% "
            f"Crude={ctx.crude_chg:+.2f}%"
            if ctx.gift_nifty_chg is not None and ctx.crude_chg is not None
            else f"🌍 Global bias: {ctx.overall_bias}"
        )

        sent = get_news_sentiment(force=True)
        logger.info(
            f"📰 News sentiment: {sent.label} (score={sent.score:+.2f}) "
            f"| Event={sent.event_bias} ({sent.event_count})"
        )

    def run_cycle(self):
        """Main strategy cycle — called every minute by scheduler."""
        self._cycle_count += 1

        # Connectivity health check every 10 cycles
        if self._cycle_count % 10 == 0:
            if not self._health_check():
                return

        vix = self.dhan.get_vix()
        if vix is None:
            logger.warning("VIX unavailable — skipping cycle")
            return

        # Fetch global context every 5 cycles (cached 5 min internally)
        ctx  = get_global_context()
        sent = get_news_sentiment()

        for index in INDICES:
            try:
                self._process_index(index, vix, ctx, sent)
            except Exception as e:
                logger.exception(f"Error processing {index}: {e}")

        s = self.engine.status()
        logger.info(
            f"💼 Capital=₹{s['available_capital']:,.0f} | "
            f"Open={s['open_positions']} | "
            f"DayP&L=₹{s['daily_pnl']:+.2f} | "
            f"Trades={s['total_trades']} | "
            f"Sentiment={sent.label}/{sent.event_bias}"
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

    def _process_index(self, index: str, vix: float, ctx, sent):
        """Fetch data and run strategy cycle for one index."""
        sid = INDEX_SECURITY_IDS.get(index)
        if not sid:
            return

        spot_price = self.dhan.get_spot_price(index)
        if not spot_price:
            logger.debug(f"{index}: spot price unavailable")
            return

        df_1min = self.dhan.get_historical(sid, interval="minute",  days_back=1)
        df_5min = self.dhan.get_historical(sid, interval="5minute", days_back=1)

        if df_1min is None or df_5min is None or len(df_1min) < 15:
            logger.debug(f"{index}: insufficient candle data")
            return

        expiry = ""
        chain_data = None
        try:
            expiry = get_nearest_weekly_expiry(self.dhan, index) or ""
            if expiry:
                chain_resp = self.dhan.get_option_chain(index, expiry)
                if chain_resp and chain_resp.get("status") != "failure":
                    chain_data = chain_resp.get("data", {})
        except Exception as e:
            logger.debug(f"{index}: option chain capture skipped ({e})")

        # Persist live market data for offline backtesting and model iteration.
        try:
            self.recorder.record_cycle(
                index=index,
                spot_price=spot_price,
                vix=vix,
                df_1min=df_1min,
                df_5min=df_5min,
                option_chain=chain_data,
                option_expiry=expiry,
                strike_step=INDICES[index]["strike_step"],
            )
        except Exception as e:
            logger.debug(f"{index}: data recorder skipped ({e})")

        self.selector.run_cycle(
            index      = index,
            spot_price = spot_price,
            vix        = vix,
            df_1min    = df_1min,
            df_5min    = df_5min,
        )

    def _health_check(self) -> bool:
        """Verify Dhan API connectivity."""
        try:
            vix = self.dhan.get_vix()
            if vix:
                return True
            logger.warning("Health check: empty VIX response")
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
@click.option("--dashboard", is_flag=True, help="Start web dashboard only (no trading)")
def main(mode: str, report: bool, weekly: bool, backtest: bool, dashboard: bool):
    """
    🤖  Nifty Options Algo Trader

    \b
    Autonomous paper-trading bot for Nifty, BankNifty, FinNifty weekly options.
    Powered by Dhan API (free). Runs hands-free 9:15 AM – 3:15 PM IST.
    All P&L reported after STT, brokerage, GST, stamp duty deduction.
    """
    if mode == "live":
        console.print("\n[bold red]⚠️  WARNING: LIVE MODE — Real orders will be placed![/bold red]")
        console.print("[red]This is NOT paper trading. Real money is at risk.[/red]\n")
        if not click.confirm("Type 'yes' to confirm LIVE mode"):
            console.print("Aborted.")
            sys.exit(0)

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

    if dashboard:
        console.print("[bold cyan]📊 Starting dashboard at http://127.0.0.1:5000[/bold cyan]")
        from dashboard.app import start_dashboard
        start_dashboard(bot=None)
        sys.exit(0)

    if not is_trading_day():
        console.print("[yellow]⚠️  Today is not a trading day (weekend/holiday). Exiting.[/yellow]")
        sys.exit(0)

    console.print(f"\n[bold cyan]🚀 Starting in {mode.upper()} mode[/bold cyan]")
    bot = AlgoBot()

    # Start dashboard in background thread
    try:
        from dashboard.app import start_dashboard
        t = threading.Thread(target=start_dashboard, args=(bot,), daemon=True)
        t.start()
        console.print("[green]📊 Dashboard: http://127.0.0.1:5000[/green]")
    except Exception as e:
        logger.warning(f"Dashboard could not start: {e}")

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
