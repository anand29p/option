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
#   python main.py --dashboard      # start Streamlit dashboard only (port 8501)
# ─────────────────────────────────────────────────────────────────────────────

import sys
import threading
import subprocess
import os
import json
import click
from datetime import datetime
from pathlib import Path
from rich.console import Console

from config.settings import (
    INDICES,
    IST,
    LOG_DIR,
    SECURITY_IDS,
    FALLBACK_VIX,
    RUNTIME_STATUS_FILE,
)
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
        self._last_good_vix: float | None = None
        self._last_good_vix_at: datetime | None = None
        self._last_vix_source = "unknown"
        self._last_spot: dict[str, float] = {}
        self._last_spot_at: dict[str, datetime] = {}
        self._heartbeat_path = Path(RUNTIME_STATUS_FILE)

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
        cycle_started_at = datetime.now(IST)
        cycle_report: dict[str, dict[str, object]] = {}

        # Connectivity health check every 10 cycles
        if self._cycle_count % 10 == 0:
            if not self._health_check():
                self._write_runtime_status(
                    cycle_started_at=cycle_started_at,
                    cycle_state="health_check_failed",
                    per_symbol=cycle_report,
                )
                return

        vix = self._resolve_vix()
        if vix is None:
            logger.warning("VIX unavailable and no recent fallback — skipping cycle")
            self._write_runtime_status(
                cycle_started_at=cycle_started_at,
                cycle_state="vix_unavailable",
                per_symbol=cycle_report,
            )
            return

        # Fetch global context every 5 cycles (cached 5 min internally)
        ctx  = get_global_context()
        sent = get_news_sentiment()

        for index in INDICES:
            try:
                cycle_report[index] = self._process_index(index, vix, ctx, sent)
            except Exception as e:
                logger.exception(f"Error processing {index}: {e}")
                cycle_report[index] = {
                    "status": "error",
                    "error": str(e),
                }

        s = self.engine.status()
        logger.info(
            f"💼 Capital=₹{s['available_capital']:,.0f} | "
            f"Open={s['open_positions']} | "
            f"DayP&L=₹{s['daily_pnl']:+.2f} | "
            f"Trades={s['total_trades']} | "
            f"Sentiment={sent.label}/{sent.event_bias}"
        )
        self._write_runtime_status(
            cycle_started_at=cycle_started_at,
            cycle_state="ok",
            per_symbol=cycle_report,
        )

    def _resolve_vix(self) -> float | None:
        """
        Resolve current VIX with short-term fallback.
        Keeps strategy loop alive during transient quote/API outages.
        """
        fresh = self.dhan.get_vix()
        if fresh is not None:
            self._last_good_vix = float(fresh)
            self._last_good_vix_at = datetime.now(IST)
            self._last_vix_source = "live"
            return float(fresh)

        if self._last_good_vix is not None and self._last_good_vix_at is not None:
            age = (datetime.now(IST) - self._last_good_vix_at).total_seconds()
            if age <= 20 * 60:
                logger.warning(
                    f"VIX fetch failed; using cached VIX={self._last_good_vix:.2f} "
                    f"({int(age)}s old)"
                )
                self._last_vix_source = "cache"
                return float(self._last_good_vix)

        logger.warning(
            f"VIX fetch failed with no cache; using fallback VIX={FALLBACK_VIX:.2f}"
        )
        self._last_vix_source = "fallback"
        return float(FALLBACK_VIX)

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

    def _process_index(self, index: str, vix: float, ctx, sent) -> dict[str, object]:
        """Fetch data and run strategy cycle for one symbol (index or stock)."""
        from config.settings import SECURITY_IDS
        
        symbol_cfg = INDICES.get(index)
        if not symbol_cfg:
            return {"status": "unknown_symbol", "spot_source": "none"}
        
        is_index = symbol_cfg.get("type") == "index"
        sid = SECURITY_IDS.get(index)
        if not sid:
            return {"status": "missing_security_id", "spot_source": "none"}

        df_1min = self.dhan.get_historical(sid, interval="minute",  days_back=1)
        df_5min = self.dhan.get_historical(sid, interval="5minute", days_back=1)

        if df_1min is None or df_5min is None or len(df_1min) < 15:
            logger.debug(f"{index}: insufficient candle data")
            return {
                "status": "insufficient_candles",
                "spot_source": "none",
                "candles_1m": 0 if df_1min is None else len(df_1min),
                "candles_5m": 0 if df_5min is None else len(df_5min),
            }

        spot_price, spot_source = self._resolve_spot_price(index, df_1min, is_index=is_index)
        if not spot_price:
            logger.debug(f"{index}: spot price unavailable")
            return {
                "status": "spot_unavailable",
                "spot_source": spot_source,
                "candles_1m": len(df_1min),
                "candles_5m": len(df_5min),
            }

        expiry = ""
        chain_data = None
        try:
            expiry = get_nearest_weekly_expiry(self.dhan, index, is_index=is_index) or ""
            if expiry:
                chain_resp = self.dhan.get_option_chain(index, expiry, is_index=is_index)
                if chain_resp and chain_resp.get("status") != "failure":
                    chain_data = chain_resp.get("data", {})
        except Exception as e:
            logger.debug(f"{index}: option chain capture skipped ({e})")

        # Persist live market data for offline backtesting and model iteration.
        try:
            self.recorder.record_cycle(
                index=index,
                spot_price=spot_price,
                vix=vix if is_index else None,
                df_1min=df_1min,
                df_5min=df_5min,
                option_chain=chain_data,
                option_expiry=expiry,
                strike_step=symbol_cfg["strike_step"],
            )
        except Exception as e:
            logger.debug(f"{index}: data recorder skipped ({e})")

        self.selector.run_cycle(
            index      = index,
            spot_price = spot_price,
            vix        = vix if is_index else None,
            df_1min    = df_1min,
            df_5min    = df_5min,
        )
        return {
            "status": "processed",
            "spot_source": spot_source,
            "spot_price": round(float(spot_price), 2),
            "candles_1m": len(df_1min),
            "candles_5m": len(df_5min),
            "option_chain": bool(chain_data),
            "expiry": expiry,
            "type": "index" if is_index else "stock",
        }

    def _resolve_spot_price(self, index: str, df_1min, is_index: bool = True) -> tuple[float | None, str]:
        """Resolve spot price from live quote, latest candle close, or short-lived cache."""
        live_spot = self.dhan.get_spot_price(index, is_index=is_index)
        if live_spot:
            self._last_spot[index] = float(live_spot)
            self._last_spot_at[index] = datetime.now(IST)
            return float(live_spot), "live"

        try:
            if df_1min is not None and not df_1min.empty and "close" in df_1min.columns:
                candle_spot = float(df_1min["close"].iloc[-1])
                if candle_spot > 0:
                    self._last_spot[index] = candle_spot
                    self._last_spot_at[index] = datetime.now(IST)
                    logger.debug(f"{index}: using latest 1m close as spot fallback ({candle_spot:.2f})")
                    return candle_spot, "1m_close"
        except Exception:
            pass

        cached_spot = self._last_spot.get(index)
        cached_at = self._last_spot_at.get(index)
        if cached_spot is not None and cached_at is not None:
            age = (datetime.now(IST) - cached_at).total_seconds()
            if age <= 15 * 60:
                logger.debug(f"{index}: using cached spot fallback ({cached_spot:.2f}, {int(age)}s old)")
                return float(cached_spot), "cache"

        return None, "none"

    def _write_runtime_status(
        self,
        cycle_started_at: datetime,
        cycle_state: str,
        per_symbol: dict[str, dict[str, object]],
    ) -> None:
        """Write lightweight heartbeat file for ops/debug/dashboard use."""
        try:
            self._heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "timestamp": datetime.now(IST).isoformat(),
                "cycle_started_at": cycle_started_at.isoformat(),
                "cycle_count": self._cycle_count,
                "cycle_state": cycle_state,
                "mode": "paper",
                "vix_source": self._last_vix_source,
                "last_good_vix": self._last_good_vix,
                "symbols": per_symbol,
                "engine": self.engine.status(),
            }
            self._heartbeat_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug(f"Runtime heartbeat write skipped: {e}")

    def _health_check(self) -> bool:
        """Verify Dhan API connectivity."""
        try:
            vix = self._resolve_vix()
            if vix is not None:
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
@click.option("--backtest-pairs", type=int, default=0, 
              help="Backtest strategy pair combinations (2 or 3) and exit. Requires number of signals.")
@click.option("--dashboard", is_flag=True, help="Start web dashboard only (no trading)")
def main(mode: str, report: bool, weekly: bool, backtest: bool, backtest_pairs: int, dashboard: bool):
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

    if backtest_pairs > 0:
        from utils.backtester import run_backtest_pairs
        if backtest_pairs not in (2, 3):
            console.print("[red]❌ --backtest-pairs requires 2 or 3[/red]")
            sys.exit(1)
        run_backtest_pairs(days=100, signal_count=backtest_pairs)
        sys.exit(0)

    if dashboard:
        console.print("[bold cyan]📊 Starting Streamlit dashboard at http://127.0.0.1:8501[/bold cyan]")
        streamlit_cmd = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "streamlit_app.py",
            "--server.address",
            "127.0.0.1",
            "--server.port",
            "8501",
            "--server.headless",
            "true",
        ]
        try:
            subprocess.run(streamlit_cmd, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to start Streamlit dashboard: {e}")
            sys.exit(1)
        sys.exit(0)

    if not is_trading_day():
        console.print("[yellow]⚠️  Today is not a trading day (weekend/holiday). Exiting.[/yellow]")
        sys.exit(0)

    console.print(f"\n[bold cyan]🚀 Starting in {mode.upper()} mode[/bold cyan]")
    bot = AlgoBot()

    # Legacy Flask dashboard is kept as optional for backward compatibility.
    if os.getenv("ENABLE_FLASK_DASHBOARD", "false").lower() in ("1", "true", "yes", "on"):
        try:
            from dashboard.app import start_dashboard
            t = threading.Thread(target=start_dashboard, args=(bot,), daemon=True)
            t.start()
            console.print("[green]📊 Flask dashboard: http://127.0.0.1:5000[/green]")
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
