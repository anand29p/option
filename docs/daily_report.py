# reports/daily_report.py
# ─────────────────────────────────────────────────────────────────────────────
# Daily & Weekly P&L Report Generator
# Reads trade log CSV → computes net P&L → saves JSON + prints rich table
# ─────────────────────────────────────────────────────────────────────────────

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich import box
from loguru import logger

from config.settings import LOG_DIR, TRADE_LOG, IST, PAPER_CAPITAL
from utils.tax_calculator import daily_tax_summary

console = Console()


def _read_trades_for_date(target_date: str) -> list[dict]:
    """Read all closed trades from the CSV log for a given date."""
    path = Path(TRADE_LOG)
    if not path.exists():
        return []

    trades = []
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["date"] == target_date:
                trades.append(row)
    return trades


def generate_daily_report(date_str: str = None) -> dict:
    """
    Generate and display the daily P&L report.

    Args:
        date_str: "YYYY-MM-DD" (defaults to today)

    Returns:
        Report dict saved to logs/YYYY-MM-DD_report.json
    """
    if date_str is None:
        date_str = datetime.now(IST).strftime("%Y-%m-%d")

    trades = _read_trades_for_date(date_str)

    if not trades:
        logger.info(f"No trades found for {date_str}")
        return {}

    # Rebuild for tax summary
    tax_input = [
        {
            "entry_price": float(t["entry_price"]),
            "exit_price":  float(t["exit_price"]) if t["exit_price"] else float(t["entry_price"]) * 0.7,
            "quantity":    int(t["quantity"]),
        }
        for t in trades
        if t.get("exit_price")
    ]

    summary = daily_tax_summary(tax_input)

    report = {
        "date":              date_str,
        "total_trades":      summary["trades"],
        "winners":           summary["winners"],
        "losers":            summary["losers"],
        "win_rate_pct":      summary["win_rate"],
        "gross_pnl":         summary["gross_pnl"],
        "charges": {
            "stt":           summary["stt"],
            "nse_txn":       summary["nse_txn"],
            "sebi_fee":      summary["sebi_fee"],
            "stamp_duty":    summary["stamp_duty"],
            "brokerage":     summary["brokerage"],
            "gst":           summary["gst"],
            "total":         summary["total_charges"],
        },
        "net_pnl":           summary["net_pnl"],
        "net_pnl_on_capital_pct": round(summary["net_pnl"] / PAPER_CAPITAL * 100, 2),
        "trades_detail":     trades,
    }

    # Save JSON
    out_path = Path(LOG_DIR) / f"{date_str}_report.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    logger.info(f"Daily report saved → {out_path}")

    # Print rich table
    _print_daily_table(report, trades)

    return report


def _print_daily_table(report: dict, trades: list[dict]):
    """Print a nicely formatted P&L table to console."""
    console.rule(f"[bold cyan]📊 Daily P&L Report — {report['date']}[/bold cyan]")

    # Summary table
    summary_table = Table(box=box.ROUNDED, show_header=False)
    summary_table.add_column("Metric", style="bold")
    summary_table.add_column("Value",  justify="right")

    pnl_color = "green" if report["net_pnl"] >= 0 else "red"

    summary_table.add_row("Total Trades",      str(report["total_trades"]))
    summary_table.add_row("Winners",           f"[green]{report['winners']}[/green]")
    summary_table.add_row("Losers",            f"[red]{report['losers']}[/red]")
    summary_table.add_row("Win Rate",          f"{report['win_rate_pct']}%")
    summary_table.add_row("Gross P&L",         f"₹{report['gross_pnl']:,.2f}")
    summary_table.add_row("─── Charges ───",   "")
    charges = report["charges"]
    summary_table.add_row("  STT",             f"₹{charges['stt']:.2f}")
    summary_table.add_row("  Brokerage",       f"₹{charges['brokerage']:.2f}")
    summary_table.add_row("  NSE Txn Charge",  f"₹{charges['nse_txn']:.2f}")
    summary_table.add_row("  GST",             f"₹{charges['gst']:.2f}")
    summary_table.add_row("  Stamp Duty",      f"₹{charges['stamp_duty']:.2f}")
    summary_table.add_row("  SEBI Fee",        f"₹{charges['sebi_fee']:.4f}")
    summary_table.add_row("  Total Charges",   f"₹{charges['total']:.2f}")
    summary_table.add_row(
        "Net P&L",
        f"[{pnl_color}]₹{report['net_pnl']:,.2f} ({report['net_pnl_on_capital_pct']}%)[/{pnl_color}]"
    )

    console.print(summary_table)

    # Trade detail table
    if trades:
        trade_table = Table(title="Trade Log", box=box.SIMPLE, show_lines=True)
        trade_table.add_column("ID",       style="dim", width=10)
        trade_table.add_column("Symbol",   width=22)
        trade_table.add_column("Strategy", width=14)
        trade_table.add_column("Entry",    justify="right")
        trade_table.add_column("Exit",     justify="right")
        trade_table.add_column("Qty",      justify="right")
        trade_table.add_column("Net P&L",  justify="right")
        trade_table.add_column("Reason",   style="dim")

        for t in trades:
            net = float(t.get("net_pnl", 0) or 0)
            color = "green" if net >= 0 else "red"
            trade_table.add_row(
                t["trade_id"],
                t["symbol"],
                t.get("strategy", ""),
                f"₹{float(t['entry_price']):.1f}",
                f"₹{float(t['exit_price']):.1f}" if t.get("exit_price") else "—",
                t["quantity"],
                f"[{color}]₹{net:.2f}[/{color}]",
                t.get("exit_reason", ""),
            )

        console.print(trade_table)


def generate_weekly_report() -> dict:
    """
    Generate a 5-day weekly summary with cumulative tax breakdown.
    Automatically detects current week (Mon–Fri).
    """
    today    = datetime.now(IST).date()
    monday   = today - timedelta(days=today.weekday())
    week_num = today.isocalendar()[1]

    all_trades   = []
    daily_pnls   = []
    total_gross  = 0.0
    total_net    = 0.0
    total_charges = 0.0
    all_charges  = {"stt": 0, "nse_txn": 0, "sebi_fee": 0,
                    "stamp_duty": 0, "brokerage": 0, "gst": 0}

    for i in range(5):
        day = monday + timedelta(days=i)
        date_str = day.strftime("%Y-%m-%d")
        trades = _read_trades_for_date(date_str)
        if not trades:
            continue

        tax_input = [
            {
                "entry_price": float(t["entry_price"]),
                "exit_price":  float(t["exit_price"]) if t["exit_price"] else float(t["entry_price"]) * 0.7,
                "quantity":    int(t["quantity"]),
            }
            for t in trades if t.get("exit_price")
        ]

        day_summary = daily_tax_summary(tax_input)
        daily_pnls.append({"date": date_str, "net_pnl": day_summary["net_pnl"]})
        total_gross   += day_summary["gross_pnl"]
        total_net     += day_summary["net_pnl"]
        total_charges += day_summary["total_charges"]
        for k in all_charges:
            all_charges[k] += day_summary.get(k, 0)
        all_trades.extend(trades)

    weekly = {
        "week":              f"Week {week_num}",
        "period":            f"{monday} to {monday + timedelta(days=4)}",
        "total_trades":      len(all_trades),
        "daily_pnl":         daily_pnls,
        "gross_pnl":         round(total_gross, 2),
        "total_charges":     round(total_charges, 2),
        "charge_breakdown":  {k: round(v, 2) for k, v in all_charges.items()},
        "net_pnl":           round(total_net, 2),
        "net_pnl_on_capital_pct": round(total_net / PAPER_CAPITAL * 100, 2),
    }

    out_path = Path(LOG_DIR) / f"week_{today.year}-W{week_num:02d}_summary.json"
    out_path.write_text(json.dumps(weekly, indent=2, default=str))
    logger.info(f"Weekly report saved → {out_path}")

    console.rule(f"[bold yellow]📅 Weekly Summary — {weekly['period']}[/bold yellow]")
    pnl_color = "green" if total_net >= 0 else "red"
    console.print(f"Total Trades:    {len(all_trades)}")
    console.print(f"Gross P&L:       ₹{total_gross:,.2f}")
    console.print(f"Total Charges:   ₹{total_charges:,.2f}")
    console.print(f"Net P&L:         [{pnl_color}]₹{total_net:,.2f} ({weekly['net_pnl_on_capital_pct']}%)[/{pnl_color}]")

    return weekly
