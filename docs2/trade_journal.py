# utils/trade_journal.py
# ─────────────────────────────────────────────────────────────────────────────
# Trade Journal
# Wraps TinyDB with query helpers for analytics, filtering, and export.
# Supports: by-date, by-strategy, by-index, by-outcome queries.
# ─────────────────────────────────────────────────────────────────────────────

from pathlib import Path
from datetime import datetime, date
from typing import Optional

from tinydb import TinyDB, Query
from loguru import logger

from config.settings import LOG_DIR, IST

DB_PATH = Path(LOG_DIR) / "paper_trades.json"


class TradeJournal:
    """
    Queryable trade database on top of TinyDB.
    All query methods return lists of dicts.
    """

    def __init__(self):
        DB_PATH.parent.mkdir(exist_ok=True)
        self._db = TinyDB(str(DB_PATH))

    # ── Queries ───────────────────────────────────────────────────────────────

    def all_trades(self) -> list[dict]:
        return self._db.all()

    def trades_on(self, target_date: Optional[date] = None) -> list[dict]:
        """All trades for a given date (defaults to today)."""
        if target_date is None:
            target_date = datetime.now(IST).date()
        date_str = str(target_date)
        T = Query()
        return self._db.search(T.date == date_str)

    def trades_by_strategy(self, strategy: str) -> list[dict]:
        T = Query()
        return self._db.search(T.strategy == strategy)

    def trades_by_index(self, index: str) -> list[dict]:
        T = Query()
        return self._db.search(T.index == index)

    def winning_trades(self) -> list[dict]:
        T = Query()
        return self._db.search(T.net_pnl >= 0)

    def losing_trades(self) -> list[dict]:
        T = Query()
        return self._db.search(T.net_pnl < 0)

    # ── Analytics ─────────────────────────────────────────────────────────────

    def strategy_performance(self) -> dict[str, dict]:
        """Per-strategy aggregated stats across all recorded trades."""
        from collections import defaultdict
        stats = defaultdict(lambda: {
            "trades": 0, "winners": 0, "net_pnl": 0.0, "charges": 0.0
        })
        for t in self._db.all():
            s = t.get("strategy", "Unknown")
            stats[s]["trades"]  += 1
            stats[s]["net_pnl"] += t.get("net_pnl", 0)
            stats[s]["charges"] += t.get("charges", 0)
            if t.get("net_pnl", 0) >= 0:
                stats[s]["winners"] += 1

        result = {}
        for s, d in stats.items():
            d["win_rate"] = round(d["winners"] / max(1, d["trades"]) * 100, 1)
            d["net_pnl"]  = round(d["net_pnl"], 2)
            d["charges"]  = round(d["charges"], 2)
            result[s] = d
        return result

    def total_net_pnl(self) -> float:
        return round(sum(t.get("net_pnl", 0) for t in self._db.all()), 2)

    def total_charges_paid(self) -> float:
        return round(sum(t.get("charges", 0) for t in self._db.all()), 2)

    def summary(self) -> dict:
        trades  = self._db.all()
        wins    = [t for t in trades if t.get("net_pnl", 0) >= 0]
        losses  = [t for t in trades if t.get("net_pnl", 0) < 0]
        return {
            "total_trades":   len(trades),
            "winners":        len(wins),
            "losers":         len(losses),
            "win_rate":       round(len(wins) / max(1, len(trades)) * 100, 1),
            "total_net_pnl":  self.total_net_pnl(),
            "total_charges":  self.total_charges_paid(),
            "best_trade":     max((t.get("net_pnl", 0) for t in trades), default=0),
            "worst_trade":    min((t.get("net_pnl", 0) for t in trades), default=0),
        }

    # ── Export ────────────────────────────────────────────────────────────────

    def export_csv(self, out_path: Optional[str] = None) -> str:
        import csv
        path = out_path or str(Path(LOG_DIR) / f"journal_export_{datetime.now(IST).strftime('%Y%m%d')}.csv")
        trades = self._db.all()
        if not trades:
            logger.warning("No trades to export")
            return path
        keys = list(trades[0].keys())
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(trades)
        logger.info(f"Journal exported → {path} ({len(trades)} trades)")
        return path

    def print_summary(self):
        from rich.console import Console
        from rich.table import Table
        from rich import box
        console = Console()
        s = self.summary()
        sp = self.strategy_performance()

        console.print("\n[bold cyan]📓 Trade Journal Summary[/bold cyan]")
        console.print(f"Total Trades: {s['total_trades']} | Win Rate: {s['win_rate']}%")
        pnl_color = "green" if s["total_net_pnl"] >= 0 else "red"
        console.print(f"Net P&L: [{pnl_color}]₹{s['total_net_pnl']:+,.2f}[/{pnl_color}] | Charges: ₹{s['total_charges']:,.2f}")

        if sp:
            table = Table(title="By Strategy", box=box.SIMPLE)
            table.add_column("Strategy",  style="cyan")
            table.add_column("Trades",    justify="right")
            table.add_column("Win Rate",  justify="right")
            table.add_column("Net P&L",   justify="right")
            for name, d in sorted(sp.items(), key=lambda x: x[1]["net_pnl"], reverse=True):
                c = "green" if d["net_pnl"] >= 0 else "red"
                table.add_row(
                    name, str(d["trades"]), f"{d['win_rate']}%",
                    f"[{c}]₹{d['net_pnl']:+,.2f}[/{c}]"
                )
            console.print(table)
