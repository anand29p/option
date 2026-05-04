# utils/backtester.py
# ─────────────────────────────────────────────────────────────────────────────
# Strategy Backtester
#
# Replays historical 1-min/5-min candles through each strategy's
# generate_signal() logic. Simulates fills at next-candle open price.
# Applies all Indian tax charges to every trade.
# Outputs per-strategy stats + HTML report.
#
# Run:  python main.py --backtest
#       python -m utils.backtester   (direct)
# ─────────────────────────────────────────────────────────────────────────────

import json
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
from loguru import logger
from rich.console import Console
from rich.table import Table
from rich import box

from config.settings import (
    INDICES, PAPER_CAPITAL, STOP_LOSS_PCT, TARGET_PCT_MIN,
    LOG_DIR, IST
)
from utils.tax_calculator import calculate_net_pnl

console = Console()

# ── Data Structures ───────────────────────────────────────────────────────────

@dataclass
class BtTrade:
    strategy:    str
    index:       str
    option_type: str
    entry_bar:   int
    entry_price: float   # simulated premium (% of spot × factor)
    exit_bar:    int     = 0
    exit_price:  float   = 0.0
    exit_reason: str     = ""
    net_pnl:     float   = 0.0
    charges:     float   = 0.0
    quantity:    int     = 1   # normalized to 1 unit for backtesting


@dataclass
class BtResult:
    strategy:       str
    index:          str
    total_trades:   int   = 0
    winners:        int   = 0
    losers:         int   = 0
    gross_pnl:      float = 0.0
    total_charges:  float = 0.0
    net_pnl:        float = 0.0
    max_drawdown:   float = 0.0
    win_rate:       float = 0.0
    avg_win:        float = 0.0
    avg_loss:       float = 0.0
    profit_factor:  float = 0.0
    trades:         list  = field(default_factory=list)


# ── Premium Simulation ────────────────────────────────────────────────────────

def _simulate_premium(spot: float, index: str, direction: str) -> float:
    """
    Estimate ATM option premium from spot price.
    Uses simplified Black-Scholes approximation: ~0.4–0.8% of spot for weekly ATM.
    This is a rough model — real backtesting requires options historical data.
    """
    pct_map = {
        "NIFTY":     0.006,   # ~0.6% of spot
        "BANKNIFTY": 0.008,   # ~0.8% of spot (more volatile)
        "FINNIFTY":  0.007,
    }
    pct = pct_map.get(index, 0.007)
    return round(spot * pct, 2)


# ── Strategy Signal Generators (standalone, no Kite dependency) ───────────────

def _signal_scalp(df: pd.DataFrame, i: int) -> str:
    """RSI + VWAP scalp signal at bar i."""
    import pandas_ta as ta
    window = df.iloc[max(0, i-30):i+1].copy()
    if len(window) < 15:
        return "NONE"
    window["rsi"]  = ta.rsi(window["close"], length=9)
    window["vwap"] = ta.vwap(window["high"], window["low"], window["close"], window["volume"])
    window["va"]   = window["volume"].rolling(20).mean()
    last, prev = window.iloc[-1], window.iloc[-2]
    if pd.isna(last["rsi"]) or pd.isna(last["vwap"]):
        return "NONE"
    vol_ok = last["volume"] > last["va"] * 1.5 if last["va"] > 0 else False
    if prev["rsi"] < 38 and last["rsi"] > prev["rsi"] and last["close"] > last["vwap"] * 1.001 and vol_ok:
        return "BUY_CE"
    if prev["rsi"] > 62 and last["rsi"] < prev["rsi"] and last["close"] < last["vwap"] * 0.999 and vol_ok:
        return "BUY_PE"
    return "NONE"


def _signal_orb(df: pd.DataFrame, i: int, orb: dict) -> str:
    """ORB breakout signal."""
    if not orb.get("set"):
        return "NONE"
    price = df["close"].iloc[i]
    if price > orb["high"] * 1.002:
        return "BUY_CE"
    if price < orb["low"] * 0.998:
        return "BUY_PE"
    return "NONE"


def _signal_mr(df: pd.DataFrame, i: int) -> str:
    """Mean reversion via Bollinger Bands."""
    import pandas_ta as ta
    window = df.iloc[max(0, i-30):i+1].copy()
    if len(window) < 22:
        return "NONE"
    bb = ta.bbands(window["close"], length=20, std=2.0)
    if bb is None or bb.empty:
        return "NONE"
    window["rsi"] = ta.rsi(window["close"], length=9)
    last = window.iloc[-1]
    bbl = bb["BBL_20_2.0"].iloc[-1]
    bbu = bb["BBU_20_2.0"].iloc[-1]
    bbm = bb["BBM_20_2.0"].iloc[-1]
    if bbm == 0:
        return "NONE"
    bw = (bbu - bbl) / bbm
    if bw > 0.005:
        return "NONE"
    if last["close"] <= bbl * 1.002 and last["rsi"] < 38:
        return "BUY_CE"
    if last["close"] >= bbu * 0.998 and last["rsi"] > 62:
        return "BUY_PE"
    return "NONE"


def _signal_supertrend(df: pd.DataFrame, i: int, state: dict) -> str:
    """SuperTrend flip signal."""
    import pandas_ta as ta
    window = df.iloc[max(0, i-20):i+1].copy()
    if len(window) < 15:
        return "NONE"
    st = ta.supertrend(window["high"], window["low"], window["close"], length=10, multiplier=3.0)
    col = "SUPERTd_10_3.0"
    if st is None or col not in st.columns:
        return "NONE"
    cur, prev_dir = int(st[col].iloc[-1]), state.get("st_dir", 0)
    vol_ok = window["volume"].iloc[-1] > window["volume"].rolling(20).mean().iloc[-1] * 1.8
    state["st_dir"] = cur
    if prev_dir == -1 and cur == 1 and vol_ok:
        return "BUY_CE"
    if prev_dir == 1 and cur == -1 and vol_ok:
        return "BUY_PE"
    return "NONE"


def _signal_ema_cross(df: pd.DataFrame, i: int, state: dict) -> str:
    """EMA crossover signal."""
    import pandas_ta as ta
    window = df.iloc[max(0, i-30):i+1].copy()
    if len(window) < 25:
        return "NONE"
    window["f"] = ta.ema(window["close"], length=9)
    window["s"] = ta.ema(window["close"], length=21)
    window["v"] = ta.vwap(window["high"], window["low"], window["close"], window["volume"])
    last, prev = window.iloc[-1], window.iloc[-2]
    n     = state.get("n", 0) + 1
    state["n"] = n
    cool  = (n - state.get("last_cross", 0)) >= 3
    if prev["f"] <= prev["s"] and last["f"] > last["s"] and last["close"] > last["v"] and cool:
        state["last_cross"] = n
        return "BUY_CE"
    if prev["f"] >= prev["s"] and last["f"] < last["s"] and last["close"] < last["v"] and cool:
        state["last_cross"] = n
        return "BUY_PE"
    return "NONE"


def _signal_vwap_rev(df: pd.DataFrame, i: int) -> str:
    """VWAP reversion signal."""
    import pandas_ta as ta
    window = df.iloc[max(0, i-25):i+1].copy()
    if len(window) < 15:
        return "NONE"
    window["vwap"] = ta.vwap(window["high"], window["low"], window["close"], window["volume"])
    window["rsi"]  = ta.rsi(window["close"], length=9)
    last, prev = window.iloc[-1], window.iloc[-2]
    if last["vwap"] == 0 or pd.isna(last["vwap"]):
        return "NONE"
    dev = (last["close"] - last["vwap"]) / last["vwap"]
    if dev < -0.005 and last["rsi"] > prev["rsi"] and last["rsi"] < 45:
        return "BUY_CE"
    if dev > 0.005 and last["rsi"] < prev["rsi"] and last["rsi"] > 55:
        return "BUY_PE"
    return "NONE"


def _signal_rsi_div(df: pd.DataFrame, i: int) -> str:
    """RSI Divergence signal."""
    import pandas_ta as ta
    window = df.iloc[max(0, i-25):i+1].copy()
    if len(window) < 20:
        return "NONE"
    window["rsi"] = ta.rsi(window["close"], length=14)
    window = window.dropna()
    if len(window) < 12:
        return "NONE"
    last   = window.iloc[-1]
    recent = window.iloc[-11:-1]
    if recent.empty:
        return "NONE"
    if last["high"] > recent["high"].max() and last["rsi"] <= recent["rsi"].max() and last["rsi"] > 55:
        return "BUY_PE"
    if last["low"] < recent["low"].min() and last["rsi"] >= recent["rsi"].min() and last["rsi"] < 45:
        return "BUY_CE"
    return "NONE"


# ── Core Backtest Engine ──────────────────────────────────────────────────────

STRATEGIES = {
    "ScalpMomentum":     _signal_scalp,
    "MeanReversion":     _signal_mr,
    "VWAPReversion":     _signal_vwap_rev,
    "RSIDivergence":     _signal_rsi_div,
    # These need state dicts:
    "SuperTrendMomentum": None,
    "EMACrossover":       None,
    "ORBBreakout":        None,
}

LOT_SIZE = 25   # Use NIFTY lot size for normalization


def _backtest_strategy(
    name: str,
    index: str,
    df: pd.DataFrame,
    signal_fn,
    state: Optional[dict] = None,
) -> BtResult:
    """Run one strategy on one index's historical data."""
    result = BtResult(strategy=name, index=index)
    open_trade: Optional[BtTrade] = None
    equity_curve = [0.0]
    peak = 0.0

    orb_state = {"set": False, "high": 0.0, "low": 0.0}

    for i in range(1, len(df)):
        bar  = df.iloc[i]
        time = df.index[i]

        # ORB: build range in first 15 bars
        if name == "ORBBreakout":
            if not orb_state["set"] and i <= 15:
                orb_state["high"] = max(orb_state.get("high", 0), bar["high"])
                orb_state["low"]  = min(orb_state.get("low", 9999999), bar["low"])
                if i == 15:
                    orb_state["set"] = True
                continue

        # EOD square-off at bar 360 (6 hrs × 60 min)
        if i % 375 == 374 and open_trade:
            prem = _simulate_premium(bar["close"], index, open_trade.option_type)
            pnl_obj = calculate_net_pnl(open_trade.entry_price, prem, LOT_SIZE)
            open_trade.exit_bar    = i
            open_trade.exit_price  = prem
            open_trade.exit_reason = "eod"
            open_trade.net_pnl     = pnl_obj.charge_breakdown["net_pnl"]
            open_trade.charges     = pnl_obj.charge_breakdown["total_charges"]
            result.trades.append(open_trade)
            open_trade = None
            # Reset ORB for next day
            orb_state = {"set": False, "high": 0.0, "low": 0.0}
            continue

        # Monitor open trade
        if open_trade:
            prem = _simulate_premium(bar["close"], index, open_trade.option_type)
            sl   = open_trade.entry_price * (1 - STOP_LOSS_PCT)
            tgt  = open_trade.entry_price * (1 + TARGET_PCT_MIN)
            reason = None
            exit_p = prem
            if prem <= sl:
                reason, exit_p = "stop_loss", sl
            elif prem >= tgt:
                reason, exit_p = "target_hit", tgt
            if reason:
                pnl_obj = calculate_net_pnl(open_trade.entry_price, exit_p, LOT_SIZE)
                open_trade.exit_bar    = i
                open_trade.exit_price  = exit_p
                open_trade.exit_reason = reason
                open_trade.net_pnl     = pnl_obj.charge_breakdown["net_pnl"]
                open_trade.charges     = pnl_obj.charge_breakdown["total_charges"]
                result.trades.append(open_trade)
                open_trade = None
            continue

        # Generate signal
        try:
            if name == "ORBBreakout":
                sig = _signal_orb(df, i, orb_state)
            elif name == "SuperTrendMomentum":
                sig = _signal_supertrend(df, i, state)
            elif name == "EMACrossover":
                sig = _signal_ema_cross(df, i, state)
            else:
                sig = signal_fn(df, i)
        except Exception:
            sig = "NONE"

        if sig == "NONE":
            continue

        # Open new trade
        entry_spot = bar["close"]
        entry_prem = _simulate_premium(entry_spot, index, sig.replace("BUY_", ""))
        if entry_prem <= 0:
            continue

        open_trade = BtTrade(
            strategy    = name,
            index       = index,
            option_type = "CE" if sig == "BUY_CE" else "PE",
            entry_bar   = i,
            entry_price = entry_prem,
            quantity    = LOT_SIZE,
        )

    # Aggregate results
    wins   = [t for t in result.trades if t.net_pnl >= 0]
    losses = [t for t in result.trades if t.net_pnl <  0]

    result.total_trades  = len(result.trades)
    result.winners       = len(wins)
    result.losers        = len(losses)
    result.gross_pnl     = sum((t.exit_price - t.entry_price) * t.quantity for t in result.trades)
    result.total_charges = sum(t.charges for t in result.trades)
    result.net_pnl       = sum(t.net_pnl for t in result.trades)
    result.win_rate      = round(len(wins) / max(1, result.total_trades) * 100, 1)
    result.avg_win       = round(sum(t.net_pnl for t in wins)   / max(1, len(wins)),   2)
    result.avg_loss      = round(sum(t.net_pnl for t in losses) / max(1, len(losses)), 2)
    gross_wins  = sum(t.net_pnl for t in wins)
    gross_losses = abs(sum(t.net_pnl for t in losses))
    result.profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else 0.0

    # Max drawdown
    equity = 0.0
    peak   = 0.0
    dd     = 0.0
    for t in result.trades:
        equity += t.net_pnl
        peak    = max(peak, equity)
        dd      = max(dd, peak - equity)
    result.max_drawdown = round(dd, 2)

    return result


# ── HTML Report ───────────────────────────────────────────────────────────────

def _generate_html_report(all_results: list[BtResult], days: int):
    rows = ""
    for r in sorted(all_results, key=lambda x: x.net_pnl, reverse=True):
        color = "#2ecc71" if r.net_pnl >= 0 else "#e74c3c"
        rows += f"""
        <tr>
          <td>{r.strategy}</td>
          <td>{r.index}</td>
          <td>{r.total_trades}</td>
          <td>{r.win_rate}%</td>
          <td>₹{r.gross_pnl:,.2f}</td>
          <td>₹{r.total_charges:,.2f}</td>
          <td style="color:{color};font-weight:bold">₹{r.net_pnl:,.2f}</td>
          <td>₹{r.max_drawdown:,.2f}</td>
          <td>{r.profit_factor}</td>
          <td>₹{r.avg_win:,.2f}</td>
          <td>₹{r.avg_loss:,.2f}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Backtest Report</title>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; background:#0f1117; color:#e0e0e0; padding:24px; }}
  h1   {{ color:#00d4aa; }}
  h2   {{ color:#7f8c8d; font-size:14px; margin-top:-10px; }}
  table {{ border-collapse:collapse; width:100%; margin-top:20px; font-size:13px; }}
  th   {{ background:#1e2130; color:#00d4aa; padding:10px 14px; text-align:left; }}
  td   {{ padding:8px 14px; border-bottom:1px solid #222; }}
  tr:hover td {{ background:#1a1f2e; }}
  .badge {{ display:inline-block; padding:3px 8px; border-radius:4px;
            background:#00d4aa22; color:#00d4aa; font-size:12px; margin:2px; }}
</style>
</head>
<body>
<h1>📊 Backtest Report — Nifty Options Algo Trader</h1>
<h2>Period: Last {days} trading days | Capital: ₹{PAPER_CAPITAL:,.0f} | All P&amp;L after charges</h2>

<p>
  <span class="badge">Strategies: 7</span>
  <span class="badge">Indices: NIFTY · BANKNIFTY · FINNIFTY</span>
  <span class="badge">Options: Weekly Buying Only</span>
  <span class="badge">Charges: STT + Brokerage + GST + Stamp Duty</span>
</p>

<table>
<thead>
  <tr>
    <th>Strategy</th><th>Index</th><th>Trades</th><th>Win Rate</th>
    <th>Gross P&amp;L</th><th>Charges</th><th>Net P&amp;L</th>
    <th>Max DD</th><th>Profit Factor</th><th>Avg Win</th><th>Avg Loss</th>
  </tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
<p style="color:#555;font-size:12px;margin-top:20px;">
⚠️ Premium values are approximated (0.6–0.8% of spot). Real results require historical options data.
Generated: {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}
</p>
</body>
</html>"""

    out = Path(LOG_DIR) / "backtest_report.html"
    out.write_text(html)
    logger.info(f"HTML report saved → {out}")
    return str(out)


# ── Entry Point ───────────────────────────────────────────────────────────────

def run_backtest(days: int = 20):
    """
    Main backtester entry point.
    Fetches historical data from Kite and runs all strategies.
    """
    from utils.kite_client import KiteClient
    kite = KiteClient()

    INDEX_TOKENS = {
        "NIFTY":     256265,
        "BANKNIFTY": 260105,
        "FINNIFTY":  257801,
    }

    console.print(f"\n[bold cyan]🔬 Running backtest — last {days} trading days[/bold cyan]")
    console.print("[dim]Fetching historical data from Kite...[/dim]\n")

    all_results: list[BtResult] = []

    for index, token in INDEX_TOKENS.items():
        console.print(f"[yellow]▶ {index}[/yellow]")

        df = kite.get_historical(token, interval="minute", days_back=days)
        if df is None or df.empty:
            logger.warning(f"No data for {index} — skipping")
            continue

        # Simple strategies (stateless)
        simple = [
            ("ScalpMomentum",  _signal_scalp),
            ("MeanReversion",  _signal_mr),
            ("VWAPReversion",  _signal_vwap_rev),
            ("RSIDivergence",  _signal_rsi_div),
            ("ORBBreakout",    None),
        ]
        for name, fn in simple:
            r = _backtest_strategy(name, index, df, fn, state={})
            all_results.append(r)
            icon = "🟢" if r.net_pnl >= 0 else "🔴"
            console.print(
                f"  {icon} {name:22s} | {r.total_trades:3d} trades | "
                f"WR={r.win_rate:5.1f}% | Net=₹{r.net_pnl:+,.0f}"
            )

        # Stateful strategies
        stateful = [
            ("SuperTrendMomentum", {"st_dir": 0}),
            ("EMACrossover",       {"n": 0, "last_cross": 0}),
        ]
        for name, state in stateful:
            r = _backtest_strategy(name, index, df, None, state=state)
            all_results.append(r)
            icon = "🟢" if r.net_pnl >= 0 else "🔴"
            console.print(
                f"  {icon} {name:22s} | {r.total_trades:3d} trades | "
                f"WR={r.win_rate:5.1f}% | Net=₹{r.net_pnl:+,.0f}"
            )

    # Summary table
    _print_summary(all_results)

    # HTML report
    html_path = _generate_html_report(all_results, days)
    console.print(f"\n[bold green]📄 Full report → {html_path}[/bold green]")

    # JSON export
    json_path = Path(LOG_DIR) / "backtest_results.json"
    export = [
        {
            "strategy":      r.strategy,
            "index":         r.index,
            "total_trades":  r.total_trades,
            "win_rate":      r.win_rate,
            "net_pnl":       round(r.net_pnl, 2),
            "total_charges": round(r.total_charges, 2),
            "max_drawdown":  r.max_drawdown,
            "profit_factor": r.profit_factor,
            "avg_win":       r.avg_win,
            "avg_loss":      r.avg_loss,
        }
        for r in all_results
    ]
    json_path.write_text(json.dumps(export, indent=2))
    logger.info(f"JSON results → {json_path}")


def _print_summary(results: list[BtResult]):
    table = Table(title="Backtest Summary (Net P&L after all charges)", box=box.ROUNDED)
    table.add_column("Strategy",       style="cyan",  width=22)
    table.add_column("Index",          width=12)
    table.add_column("Trades",         justify="right")
    table.add_column("Win Rate",       justify="right")
    table.add_column("Net P&L",        justify="right")
    table.add_column("Max DD",         justify="right")
    table.add_column("P-Factor",       justify="right")

    for r in sorted(results, key=lambda x: x.net_pnl, reverse=True):
        color  = "green" if r.net_pnl >= 0 else "red"
        table.add_row(
            r.strategy, r.index,
            str(r.total_trades),
            f"{r.win_rate}%",
            f"[{color}]₹{r.net_pnl:+,.0f}[/{color}]",
            f"₹{r.max_drawdown:,.0f}",
            str(r.profit_factor),
        )
    console.print(table)


if __name__ == "__main__":
    run_backtest(days=20)
