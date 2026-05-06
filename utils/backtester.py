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
from utils.market_data_recorder import load_recorded_ohlcv, load_recorded_atm_options

console = Console()

# ── Data Structures ───────────────────────────────────────────────────────────

@dataclass
class BtTrade:
    strategy:    str
    index:       str
    option_type: str
    entry_bar:   int
    entry_spot:  float
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


def _mark_premium(trade: BtTrade, spot: float) -> float:
    """Mark an open ATM option with direction-aware delta movement."""
    delta = 0.50
    spot_move = spot - trade.entry_spot
    directional_move = spot_move if trade.option_type == "CE" else -spot_move
    premium = trade.entry_price + delta * directional_move
    floor = trade.entry_price * 0.10
    return round(max(floor, premium), 2)


def _volume_ok(last: pd.Series, multiplier: float) -> bool:
    """Return true when volume confirms, or when index volume is unavailable."""
    vol = float(last.get("volume", 0) or 0)
    avg = float(last.get("vol_avg", last.get("va", 0)) or 0)
    if vol <= 0 or avg <= 0:
        return True
    return vol > avg * multiplier


def _lookup_recorded_option_price(
    option_df: Optional[pd.DataFrame],
    ts: datetime,
    option_type: str,
    spot_price: float,
    max_lag_minutes: int = 3,
) -> Optional[float]:
    """Lookup nearest recorded ATM option premium around timestamp."""
    if option_df is None or option_df.empty:
        return None

    try:
        if option_df.index.tz is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=option_df.index.tz)
    except Exception:
        pass

    # Keep a narrow time window to avoid stale premium marks.
    win = option_df[(option_df.index >= ts - timedelta(minutes=max_lag_minutes)) & (option_df.index <= ts + timedelta(minutes=1))]
    if win.empty:
        return None

    pick = win.iloc[-1]
    col = "ce_ltp" if option_type == "CE" else "pe_ltp"
    value = pick.get(col)
    try:
        price = float(value)
        if price > 0:
            return price
    except Exception:
        return None
    return None


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
    vol_ok = _volume_ok(last, 1.5)
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
    state["vol_avg"] = window["volume"].rolling(20).mean().iloc[-1]
    vol_ok = _volume_ok(pd.Series({"volume": window["volume"].iloc[-1], "vol_avg": state["vol_avg"]}), 1.8)
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


def _signal_trend_rider(df: pd.DataFrame, i: int) -> str:
    """EMA/VWAP aligned breakout with RSI confirmation."""
    import pandas_ta as ta
    window = df.iloc[max(0, i-70):i+1].copy()
    if len(window) < 55:
        return "NONE"
    window["ema20"] = ta.ema(window["close"], length=20)
    window["ema50"] = ta.ema(window["close"], length=50)
    window["vwap"] = ta.vwap(window["high"], window["low"], window["close"], window["volume"])
    window["rsi"] = ta.rsi(window["close"], length=14)
    last = window.iloc[-1]
    prior = window.iloc[-21:-1]
    if prior.empty or pd.isna(last["ema50"]) or pd.isna(last["vwap"]):
        return "NONE"
    if (
        last["ema20"] > last["ema50"]
        and last["close"] > last["vwap"]
        and 54 <= last["rsi"] <= 72
        and last["close"] > prior["high"].max()
    ):
        return "BUY_CE"
    if (
        last["ema20"] < last["ema50"]
        and last["close"] < last["vwap"]
        and 28 <= last["rsi"] <= 46
        and last["close"] < prior["low"].min()
    ):
        return "BUY_PE"
    return "NONE"


def _signal_vwap_reclaim(df: pd.DataFrame, i: int) -> str:
    """Trade VWAP reclaim/rejection only when the short trend agrees."""
    import pandas_ta as ta
    window = df.iloc[max(0, i-45):i+1].copy()
    if len(window) < 30:
        return "NONE"
    window["ema9"] = ta.ema(window["close"], length=9)
    window["ema21"] = ta.ema(window["close"], length=21)
    window["vwap"] = ta.vwap(window["high"], window["low"], window["close"], window["volume"])
    window["rsi"] = ta.rsi(window["close"], length=14)
    window["vol_avg"] = window["volume"].rolling(20).mean()
    last, prev = window.iloc[-1], window.iloc[-2]
    vol_ok = _volume_ok(last, 1.15)
    if prev["close"] <= prev["vwap"] and last["close"] > last["vwap"] and last["ema9"] > last["ema21"] and last["rsi"] > 52 and vol_ok:
        return "BUY_CE"
    if prev["close"] >= prev["vwap"] and last["close"] < last["vwap"] and last["ema9"] < last["ema21"] and last["rsi"] < 48 and vol_ok:
        return "BUY_PE"
    return "NONE"


def _signal_opening_drive(df: pd.DataFrame, i: int) -> str:
    """Stricter opening range breakout after the first 30 candles."""
    import pandas_ta as ta
    day_start = i - (i % 375)
    if i < day_start + 31 or i > day_start + 120:
        return "NONE"
    opening = df.iloc[day_start:day_start + 30]
    if len(opening) < 30:
        return "NONE"
    window = df.iloc[max(day_start, i-35):i+1].copy()
    window["vwap"] = ta.vwap(window["high"], window["low"], window["close"], window["volume"])
    window["vol_avg"] = window["volume"].rolling(20).mean()
    last = window.iloc[-1]
    vol_ok = _volume_ok(last, 1.25)
    if last["close"] > opening["high"].max() * 1.001 and last["close"] > last["vwap"] and vol_ok:
        return "BUY_CE"
    if last["close"] < opening["low"].min() * 0.999 and last["close"] < last["vwap"] and vol_ok:
        return "BUY_PE"
    return "NONE"


def _signal_bb_reversal(df: pd.DataFrame, i: int) -> str:
    """Bollinger reversal without the existing squeeze-only restriction."""
    import pandas_ta as ta
    window = df.iloc[max(0, i-35):i+1].copy()
    if len(window) < 25:
        return "NONE"
    bb = ta.bbands(window["close"], length=20, std=2.0)
    window["rsi"] = ta.rsi(window["close"], length=14)
    last, prev = window.iloc[-1], window.iloc[-2]
    lower = bb["BBL_20_2.0"].iloc[-1]
    upper = bb["BBU_20_2.0"].iloc[-1]
    if prev["close"] < lower and last["close"] > lower and last["rsi"] < 45:
        return "BUY_CE"
    if prev["close"] > upper and last["close"] < upper and last["rsi"] > 55:
        return "BUY_PE"
    return "NONE"


# ── Core Backtest Engine ──────────────────────────────────────────────────────

STRATEGIES = {
    "ScalpMomentum":     _signal_scalp,
    "MeanReversion":     _signal_mr,
    "VWAPReversion":     _signal_vwap_rev,
    "RSIDivergence":     _signal_rsi_div,
    "TrendRider":        _signal_trend_rider,
    "VWAPReclaim":       _signal_vwap_reclaim,
    "OpeningDrive":      _signal_opening_drive,
    "BollingerReversal": _signal_bb_reversal,
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
    option_df: Optional[pd.DataFrame] = None,
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
            prem = _lookup_recorded_option_price(
                option_df=option_df,
                ts=time,
                option_type=open_trade.option_type,
                spot_price=float(bar["close"]),
            )
            if prem is None:
                prem = _mark_premium(open_trade, bar["close"])
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
            prem = _lookup_recorded_option_price(
                option_df=option_df,
                ts=time,
                option_type=open_trade.option_type,
                spot_price=float(bar["close"]),
            )
            if prem is None:
                prem = _mark_premium(open_trade, bar["close"])
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
        option_type = "CE" if sig == "BUY_CE" else "PE"
        entry_prem = _lookup_recorded_option_price(
            option_df=option_df,
            ts=time,
            option_type=option_type,
            spot_price=float(entry_spot),
        )
        if entry_prem is None:
            entry_prem = _simulate_premium(entry_spot, index, option_type)
        if entry_prem <= 0:
            continue

        open_trade = BtTrade(
            strategy    = name,
            index       = index,
            option_type = option_type,
            entry_bar   = i,
            entry_spot  = entry_spot,
            entry_price = entry_prem,
            quantity    = LOT_SIZE,
        )

    if open_trade:
        bar = df.iloc[-1]
        prem = _lookup_recorded_option_price(
            option_df=option_df,
            ts=df.index[-1],
            option_type=open_trade.option_type,
            spot_price=float(bar["close"]),
        )
        if prem is None:
            prem = _mark_premium(open_trade, bar["close"])
        pnl_obj = calculate_net_pnl(open_trade.entry_price, prem, LOT_SIZE)
        open_trade.exit_bar = len(df) - 1
        open_trade.exit_price = prem
        open_trade.exit_reason = "final_bar"
        open_trade.net_pnl = pnl_obj.charge_breakdown["net_pnl"]
        open_trade.charges = pnl_obj.charge_breakdown["total_charges"]
        result.trades.append(open_trade)

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
⚠️ Backtester prefers recorded ATM option premiums from logs/market_data when present; otherwise it falls back to spot-based premium approximation.
Generated: {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}
</p>
</body>
</html>"""

    out = Path(LOG_DIR) / "backtest_report.html"
    out.write_text(html, encoding="utf-8")
    logger.info(f"HTML report saved → {out}")
    return str(out)


def _safe_write_csv(df: pd.DataFrame, filename: str) -> str:
    """Write CSV to logs directory, falling back to a timestamped filename if needed."""
    out = Path(LOG_DIR) / filename
    try:
        df.to_csv(out, index=False)
    except PermissionError:
        stamp = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
        out = Path(LOG_DIR) / f"{out.stem}_{stamp}{out.suffix}"
        df.to_csv(out, index=False)
    return str(out)


def _export_csv_results(all_results: list[BtResult], days: int) -> tuple[Optional[str], Optional[str]]:
    """Persist summary and per-trade backtest results as CSV files."""
    generated_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    summary_rows = [
        {
            "generated_at": generated_at,
            "days": days,
            "strategy": r.strategy,
            "index": r.index,
            "total_trades": r.total_trades,
            "winners": r.winners,
            "losers": r.losers,
            "win_rate": r.win_rate,
            "gross_pnl": round(r.gross_pnl, 2),
            "total_charges": round(r.total_charges, 2),
            "net_pnl": round(r.net_pnl, 2),
            "max_drawdown": r.max_drawdown,
            "profit_factor": r.profit_factor,
            "avg_win": r.avg_win,
            "avg_loss": r.avg_loss,
        }
        for r in all_results
    ]

    trade_rows = [
        {
            "generated_at": generated_at,
            "days": days,
            "strategy": t.strategy,
            "index": t.index,
            "option_type": t.option_type,
            "entry_bar": t.entry_bar,
            "entry_spot": round(t.entry_spot, 2),
            "entry_price": round(t.entry_price, 2),
            "exit_bar": t.exit_bar,
            "exit_price": round(t.exit_price, 2),
            "exit_reason": t.exit_reason,
            "net_pnl": round(t.net_pnl, 2),
            "charges": round(t.charges, 2),
            "quantity": t.quantity,
        }
        for r in all_results
        for t in r.trades
    ]

    summary_path = None
    trades_path = None

    if summary_rows:
        summary_df = pd.DataFrame(summary_rows).sort_values(
            by=["net_pnl", "win_rate"],
            ascending=[False, False],
        )
        summary_path = _safe_write_csv(summary_df, "backtest_results.csv")
        logger.info(f"CSV summary → {summary_path}")

    if trade_rows:
        trades_df = pd.DataFrame(trade_rows).sort_values(
            by=["strategy", "index", "entry_bar"],
            ascending=[True, True, True],
        )
        trades_path = _safe_write_csv(trades_df, "backtest_trades.csv")
        logger.info(f"CSV trades → {trades_path}")

    return summary_path, trades_path


# ── Entry Point ───────────────────────────────────────────────────────────────

def _fetch_yfinance(ticker: str, period: str = "5d", interval: str = "1m") -> Optional[pd.DataFrame]:
    """Fetch OHLCV from yfinance and normalise column names to lowercase."""
    try:
        import yfinance as yf
        cache_dir = Path(LOG_DIR) / "yfinance_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        yf.set_tz_cache_location(str(cache_dir))
        raw = yf.download(ticker, period=period, interval=interval,
                          progress=False, auto_adjust=True)
        if raw is None or raw.empty:
            return None
        # yfinance may return multi-level columns — flatten them
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0].lower() for c in raw.columns]
        else:
            raw.columns = [c.lower() for c in raw.columns]
        raw = raw.rename(columns={"adj close": "close"})
        for col in ("open", "high", "low", "close", "volume"):
            if col not in raw.columns:
                raw[col] = raw.get("close", 0)
        return raw[["open", "high", "low", "close", "volume"]].dropna()
    except Exception as e:
        logger.error(f"yfinance fetch failed for {ticker}: {e}")
        return None


def _fetch_dhan(client, index: str, days: int) -> Optional[pd.DataFrame]:
    """Fetch index candles from Dhan when yfinance is unavailable.

    Uses chunked date windows because large single-range minute requests can fail.
    """
    try:
        from utils.dhan_client import DhanClient

        if client is None:
            client = DhanClient()
        sid = DhanClient.INDEX_SECURITY_IDS.get(index)
        if not sid:
            return None

        to_date = datetime.now(IST)
        from_date = to_date - timedelta(days=max(days + 2, 7))
        chunk_days = 7
        frames: list[pd.DataFrame] = []

        cursor = from_date
        while cursor <= to_date:
            chunk_end = min(cursor + timedelta(days=chunk_days - 1), to_date)
            df = client.get_historical_range(
                security_id=sid,
                from_date=cursor,
                to_date=chunk_end,
                interval="minute",
                exchange=DhanClient.IDX_I,
                instrument_type="INDEX",
            )
            if df is not None and not df.empty:
                frames.append(df)
            cursor = chunk_end + timedelta(days=1)

        if not frames:
            return None

        out = pd.concat(frames).sort_index()
        out = out[~out.index.duplicated(keep="last")]
        return out
    except Exception as e:
        logger.error(f"Dhan historical fetch failed for {index}: {e}")
        return None


def run_backtest(days: int = 5):
    """
    Main backtester entry point.
    Uses local recorded candles first, then Dhan Data API for historical fallback.
    """
    indices = ["NIFTY", "BANKNIFTY", "FINNIFTY"]

    console.print(f"\n[bold cyan]🔬 Running backtest — last {days} trading days[/bold cyan]")
    console.print("[dim]Trying local recorded candles first, then Dhan Data API fallback...[/dim]\n")

    all_results: list[BtResult] = []
    dhan_client = None

    for index in indices:
        console.print(f"[yellow]▶ {index}[/yellow]")

        df = load_recorded_ohlcv(index=index, days=days)
        option_df = load_recorded_atm_options(index=index, days=days)
        if df is not None and not df.empty:
            logger.info(f"Using recorded local data for {index}: {len(df)} candles")
            if option_df is not None and not option_df.empty:
                logger.info(f"Using recorded ATM option premiums for {index}: {len(option_df)} rows")
        if df is None or df.empty:
            df = _fetch_dhan(dhan_client, index, days)
        if df is None or df.empty:
            logger.warning(f"No data for {index} — skipping")
            continue

        # Simple strategies (stateless)
        simple = [
            ("ScalpMomentum",  _signal_scalp),
            ("MeanReversion",  _signal_mr),
            ("VWAPReversion",  _signal_vwap_rev),
            ("RSIDivergence",  _signal_rsi_div),
            ("TrendRider",     _signal_trend_rider),
            ("VWAPReclaim",    _signal_vwap_reclaim),
            ("OpeningDrive",   _signal_opening_drive),
            ("BollingerReversal", _signal_bb_reversal),
            ("ORBBreakout",    None),
        ]
        for name, fn in simple:
            r = _backtest_strategy(name, index, df, fn, state={}, option_df=option_df)
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
            r = _backtest_strategy(name, index, df, None, state=state, option_df=option_df)
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

    # CSV exports
    summary_csv_path, trades_csv_path = _export_csv_results(all_results, days)
    if summary_csv_path:
        console.print(f"[bold green]🧾 CSV summary → {summary_csv_path}[/bold green]")
    if trades_csv_path:
        console.print(f"[bold green]🧾 CSV trades → {trades_csv_path}[/bold green]")

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
    try:
        json_path.write_text(json.dumps(export, indent=2))
    except PermissionError:
        stamp = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
        json_path = Path(LOG_DIR) / f"backtest_results_{stamp}.json"
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
    run_backtest(days=5)
