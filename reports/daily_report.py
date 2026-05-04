# reports/daily_report.py
import csv, json
from datetime import datetime, timedelta
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich import box
from loguru import logger
from config.settings import LOG_DIR, TRADE_LOG, IST, PAPER_CAPITAL
from utils.tax_calculator import daily_tax_summary

console = Console()


def _read_trades_for_date(target_date: str) -> list:
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
    if date_str is None:
        date_str = datetime.now(IST).strftime("%Y-%m-%d")
    trades = _read_trades_for_date(date_str)
    if not trades:
        logger.info(f"No trades found for {date_str}")
        return {}
    tax_input = [
        {"entry_price": float(t["entry_price"]),
         "exit_price": float(t["exit_price"]) if t["exit_price"] else float(t["entry_price"]) * 0.7,
         "quantity": int(t["quantity"])}
        for t in trades if t.get("exit_price")
    ]
    summary = daily_tax_summary(tax_input)
    report = {
        "date": date_str, "total_trades": summary["trades"],
        "winners": summary["winners"], "losers": summary["losers"],
        "win_rate_pct": summary["win_rate"], "gross_pnl": summary["gross_pnl"],
        "charges": {
            "stt": summary["stt"], "nse_txn": summary["nse_txn"],
            "sebi_fee": summary["sebi_fee"], "stamp_duty": summary["stamp_duty"],
            "brokerage": summary["brokerage"], "gst": summary["gst"],
            "total": summary["total_charges"],
        },
        "net_pnl": summary["net_pnl"],
        "net_pnl_on_capital_pct": round(summary["net_pnl"] / PAPER_CAPITAL * 100, 2),
        "trades_detail": trades,
    }
    out_path = Path(LOG_DIR) / f"{date_str}_report.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    logger.info(f"Daily report saved → {out_path}")
    _print_daily_table(report, trades)
    return report


def _print_daily_table(report: dict, trades: list):
    console.rule(f"[bold cyan]📊 Daily P&L Report — {report['date']}[/bold cyan]")
    t = Table(box=box.ROUNDED, show_header=False)
    t.add_column("Metric", style="bold")
    t.add_column("Value", justify="right")
    pnl_color = "green" if report["net_pnl"] >= 0 else "red"
    t.add_row("Total Trades", str(report["total_trades"]))
    t.add_row("Winners", f"[green]{report['winners']}[/green]")
    t.add_row("Losers", f"[red]{report['losers']}[/red]")
    t.add_row("Win Rate", f"{report['win_rate_pct']}%")
    t.add_row("Gross P&L", f"₹{report['gross_pnl']:,.2f}")
    charges = report["charges"]
    t.add_row("STT", f"₹{charges['stt']:.2f}")
    t.add_row("Brokerage", f"₹{charges['brokerage']:.2f}")
    t.add_row("GST", f"₹{charges['gst']:.2f}")
    t.add_row("Total Charges", f"₹{charges['total']:.2f}")
    t.add_row("Net P&L", f"[{pnl_color}]₹{report['net_pnl']:,.2f} ({report['net_pnl_on_capital_pct']}%)[/{pnl_color}]")
    console.print(t)


def generate_weekly_report() -> dict:
    today = datetime.now(IST).date()
    monday = today - timedelta(days=today.weekday())
    week_num = today.isocalendar()[1]
    all_trades, daily_pnls = [], []
    total_gross = total_net = total_charges = 0.0
    all_charges = {"stt": 0, "nse_txn": 0, "sebi_fee": 0, "stamp_duty": 0, "brokerage": 0, "gst": 0}
    for i in range(5):
        day = monday + timedelta(days=i)
        date_str = day.strftime("%Y-%m-%d")
        trades = _read_trades_for_date(date_str)
        if not trades:
            continue
        tax_input = [
            {"entry_price": float(t["entry_price"]),
             "exit_price": float(t["exit_price"]) if t["exit_price"] else float(t["entry_price"]) * 0.7,
             "quantity": int(t["quantity"])}
            for t in trades if t.get("exit_price")
        ]
        ds = daily_tax_summary(tax_input)
        daily_pnls.append({"date": date_str, "net_pnl": ds["net_pnl"]})
        total_gross += ds["gross_pnl"]
        total_net += ds["net_pnl"]
        total_charges += ds["total_charges"]
        for k in all_charges:
            all_charges[k] += ds.get(k, 0)
        all_trades.extend(trades)
    weekly = {
        "week": f"Week {week_num}",
        "period": f"{monday} to {monday + timedelta(days=4)}",
        "total_trades": len(all_trades), "daily_pnl": daily_pnls,
        "gross_pnl": round(total_gross, 2), "total_charges": round(total_charges, 2),
        "charge_breakdown": {k: round(v, 2) for k, v in all_charges.items()},
        "net_pnl": round(total_net, 2),
        "net_pnl_on_capital_pct": round(total_net / PAPER_CAPITAL * 100, 2),
    }
    out_path = Path(LOG_DIR) / f"week_{today.year}-W{week_num:02d}_summary.json"
    out_path.write_text(json.dumps(weekly, indent=2, default=str))
    logger.info(f"Weekly report saved → {out_path}")
    pnl_color = "green" if total_net >= 0 else "red"
    console.rule(f"[bold yellow]📅 Weekly Summary — {weekly['period']}[/bold yellow]")
    console.print(f"Total Trades:  {len(all_trades)}")
    console.print(f"Gross P&L:     ₹{total_gross:,.2f}")
    console.print(f"Total Charges: ₹{total_charges:,.2f}")
    console.print(f"Net P&L:       [{pnl_color}]₹{total_net:,.2f} ({weekly['net_pnl_on_capital_pct']}%)[/{pnl_color}]")
    return weekly
