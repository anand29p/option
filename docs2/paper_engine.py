# utils/paper_engine.py
# ─────────────────────────────────────────────────────────────────────────────
# Paper Trade Execution Engine
# - Simulates fills using real-time Kite LTP
# - Tracks open/closed positions in memory + CSV + TinyDB
# - Applies trailing stops dynamically
# - Enforces all risk limits before entry
# ─────────────────────────────────────────────────────────────────────────────

import uuid
import csv
import json
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger
from tinydb import TinyDB, Query

from config.settings import (
    PAPER_CAPITAL, MAX_SIMULTANEOUS_TRADES,
    STOP_LOSS_PCT, TARGET_PCT_MIN,
    MAX_DAILY_LOSS, LOG_DIR, TRADE_LOG, IST
)
from utils.tax_calculator import calculate_net_pnl, TradePnL

Path(LOG_DIR).mkdir(exist_ok=True)


@dataclass
class Position:
    """One open paper trade position."""
    trade_id:       str
    symbol:         str
    index:          str
    option_type:    str       # CE | PE
    strike:         int
    expiry:         str
    entry_price:    float
    quantity:       int
    lots:           int
    entry_time:     datetime
    stop_loss:      float     # Dynamic — updated by trailing stop logic
    target:         float
    strategy:       str
    status:         str = "OPEN"
    exit_price:     float = 0.0
    exit_time:      Optional[datetime] = None
    exit_reason:    str = ""
    pnl:            Optional[TradePnL] = field(default=None, repr=False)
    peak_price:     float = 0.0   # Highest LTP seen — used for trailing stop


class PaperEngine:
    """
    Autonomous paper trading engine.
    Maintains virtual capital, open/closed positions, trade log.
    """

    def __init__(self, kite_client):
        self.kite          = kite_client
        self.capital       = PAPER_CAPITAL
        self.open_trades:   dict[str, Position] = {}
        self.closed_trades: list[Position]      = []
        self.daily_pnl     = 0.0
        self._db           = TinyDB(f"{LOG_DIR}/paper_trades.json")
        self._init_csv_log()
        logger.info(f"📋 PaperEngine ready | Capital ₹{self.capital:,.0f}")

    # ── Day Reset ─────────────────────────────────────────────────────────────

    def reset_day(self):
        """Call at pre-market to reset daily counters."""
        self.daily_pnl = 0.0
        logger.info("PaperEngine: daily P&L counter reset")

    # ── CSV Log ───────────────────────────────────────────────────────────────

    def _init_csv_log(self):
        self._csv_path = Path(TRADE_LOG)
        if not self._csv_path.exists():
            with open(self._csv_path, "w", newline="") as f:
                csv.writer(f).writerow([
                    "trade_id", "date", "symbol", "index", "option_type",
                    "strike", "expiry", "strategy", "lots", "quantity",
                    "entry_price", "entry_time", "exit_price", "exit_time",
                    "exit_reason", "gross_pnl", "total_charges", "net_pnl",
                    "net_pnl_pct", "stt", "brokerage", "gst",
                ])

    def _append_csv(self, pos: Position):
        bd = pos.pnl.charge_breakdown if pos.pnl else {}
        with open(self._csv_path, "a", newline="") as f:
            csv.writer(f).writerow([
                pos.trade_id,
                pos.entry_time.strftime("%Y-%m-%d"),
                pos.symbol, pos.index, pos.option_type,
                pos.strike, pos.expiry, pos.strategy,
                pos.lots, pos.quantity,
                round(pos.entry_price, 2),
                pos.entry_time.strftime("%H:%M:%S"),
                round(pos.exit_price, 2),
                pos.exit_time.strftime("%H:%M:%S") if pos.exit_time else "",
                pos.exit_reason,
                bd.get("gross_pnl", ""),
                bd.get("total_charges", ""),
                bd.get("net_pnl", ""),
                bd.get("net_pnl_pct", ""),
                bd.get("stt", ""),
                bd.get("brokerage", ""),
                bd.get("gst", ""),
            ])

    def _persist_db(self, pos: Position):
        """Save closed trade to TinyDB for cross-session querying."""
        bd = pos.pnl.charge_breakdown if pos.pnl else {}
        self._db.insert({
            "trade_id":    pos.trade_id,
            "date":        pos.entry_time.strftime("%Y-%m-%d"),
            "symbol":      pos.symbol,
            "index":       pos.index,
            "option_type": pos.option_type,
            "strike":      pos.strike,
            "expiry":      pos.expiry,
            "strategy":    pos.strategy,
            "lots":        pos.lots,
            "quantity":    pos.quantity,
            "entry_price": pos.entry_price,
            "exit_price":  pos.exit_price,
            "exit_reason": pos.exit_reason,
            "net_pnl":     bd.get("net_pnl", 0),
            "charges":     bd.get("total_charges", 0),
        })

    # ── Capital Guards ────────────────────────────────────────────────────────

    def can_trade(self) -> tuple[bool, str]:
        if self.daily_pnl <= -MAX_DAILY_LOSS:
            return False, f"Daily loss limit hit (₹{self.daily_pnl:.0f} ≤ -₹{MAX_DAILY_LOSS})"
        if len(self.open_trades) >= MAX_SIMULTANEOUS_TRADES:
            return False, f"Max {MAX_SIMULTANEOUS_TRADES} positions open"
        return True, "OK"

    def available_capital(self) -> float:
        locked = sum(p.entry_price * p.quantity for p in self.open_trades.values())
        return max(0.0, self.capital - locked)

    # ── Entry ─────────────────────────────────────────────────────────────────

    def enter_trade(
        self,
        symbol:      str,
        index:       str,
        option_type: str,
        strike:      int,
        expiry:      str,
        lots:        int,
        lot_size:    int,
        strategy:    str,
    ) -> Optional[Position]:
        ok, reason = self.can_trade()
        if not ok:
            logger.warning(f"⛔ Trade blocked: {reason}")
            return None

        ltp = self._fetch_ltp(symbol)
        if ltp is None or ltp <= 0:
            logger.warning(f"⚠️  LTP unavailable for {symbol}")
            return None

        quantity    = lots * lot_size
        capital_req = ltp * quantity

        if capital_req > self.available_capital():
            logger.warning(
                f"⛔ Capital short: need ₹{capital_req:.0f}, "
                f"have ₹{self.available_capital():.0f}"
            )
            return None

        sl     = round(ltp * (1 - STOP_LOSS_PCT), 2)
        target = round(ltp * (1 + TARGET_PCT_MIN), 2)

        pos = Position(
            trade_id    = str(uuid.uuid4())[:8].upper(),
            symbol      = symbol,
            index       = index,
            option_type = option_type,
            strike      = strike,
            expiry      = expiry,
            entry_price = ltp,
            quantity    = quantity,
            lots        = lots,
            entry_time  = datetime.now(IST),
            stop_loss   = sl,
            target      = target,
            strategy    = strategy,
            peak_price  = ltp,
        )

        self.open_trades[pos.trade_id] = pos
        logger.info(
            f"✅ ENTRY [{pos.trade_id}] {symbol} | "
            f"LTP=₹{ltp} Qty={quantity} SL=₹{sl} Target=₹{target} | "
            f"Capital deployed=₹{capital_req:.0f}"
        )
        return pos

    # ── Exit ──────────────────────────────────────────────────────────────────

    def exit_trade(self, trade_id: str, reason: str = "manual") -> Optional[TradePnL]:
        pos = self.open_trades.get(trade_id)
        if not pos:
            logger.error(f"Trade {trade_id} not in open_trades")
            return None

        ltp = self._fetch_ltp(pos.symbol)
        if ltp is None:
            ltp = pos.stop_loss   # Worst-case: assume SL hit
            logger.warning(f"LTP unavailable at exit — using SL fallback ₹{ltp}")

        pos.exit_price  = ltp
        pos.exit_time   = datetime.now(IST)
        pos.exit_reason = reason
        pos.status      = "CLOSED"
        pos.pnl         = calculate_net_pnl(pos.entry_price, ltp, pos.quantity)

        net = pos.pnl.charge_breakdown["net_pnl"]
        self.daily_pnl += net
        self.capital   += net   # Update virtual capital

        del self.open_trades[trade_id]
        self.closed_trades.append(pos)
        self._append_csv(pos)
        self._persist_db(pos)

        icon = "🟢" if net >= 0 else "🔴"
        logger.info(
            f"{icon} EXIT [{trade_id}] {pos.symbol} | "
            f"Entry=₹{pos.entry_price} → Exit=₹{ltp} | "
            f"Net=₹{net:+.2f} | Reason={reason}"
        )
        return pos.pnl

    # ── Monitor ───────────────────────────────────────────────────────────────

    def monitor_positions(self):
        """
        Check all open positions for SL / Target / trailing stop.
        Called every minute by scheduler.
        """
        for trade_id, pos in list(self.open_trades.items()):
            ltp = self._fetch_ltp(pos.symbol)
            if ltp is None:
                continue

            # Update peak price for trailing stop
            if ltp > pos.peak_price:
                pos.peak_price = ltp

            # Compute trailing stop based on peak gain
            gain_pct = (pos.peak_price - pos.entry_price) / pos.entry_price
            if gain_pct >= 0.25:
                trailing_sl = pos.entry_price * 1.10   # Lock in 10%
            elif gain_pct >= 0.15:
                trailing_sl = pos.entry_price * 1.00   # Breakeven
            else:
                trailing_sl = pos.entry_price * (1 - STOP_LOSS_PCT)

            # Move SL up if trailing is higher
            if trailing_sl > pos.stop_loss:
                logger.debug(
                    f"[{trade_id}] Trail SL: ₹{pos.stop_loss:.1f} → ₹{trailing_sl:.1f}"
                )
                pos.stop_loss = trailing_sl

            # Exit checks
            if ltp <= pos.stop_loss:
                self.exit_trade(trade_id, reason="stop_loss")
            elif ltp >= pos.target:
                self.exit_trade(trade_id, reason="target_hit")

    def squareoff_all(self):
        """Force exit all positions — called at EOD."""
        count = len(self.open_trades)
        if count == 0:
            logger.info("No open positions to square off")
            return
        logger.info(f"Squaring off {count} open position(s)")
        for trade_id in list(self.open_trades.keys()):
            self.exit_trade(trade_id, reason="eod_squareoff")

    # ── LTP ───────────────────────────────────────────────────────────────────

    def _fetch_ltp(self, symbol: str) -> Optional[float]:
        try:
            data = self.kite.get_ltp([f"NFO:{symbol}"])
            return data.get(f"NFO:{symbol}")
        except Exception as e:
            logger.error(f"LTP fetch error for {symbol}: {e}")
            return None

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "capital":           round(self.capital, 2),
            "available_capital": round(self.available_capital(), 2),
            "open_positions":    len(self.open_trades),
            "daily_pnl":         round(self.daily_pnl, 2),
            "total_trades":      len(self.closed_trades),
        }

    def open_positions_summary(self) -> list[dict]:
        """Return list of open positions as plain dicts for display."""
        result = []
        for pos in self.open_trades.values():
            ltp = self._fetch_ltp(pos.symbol) or pos.entry_price
            unreal = (ltp - pos.entry_price) * pos.quantity
            result.append({
                "trade_id":    pos.trade_id,
                "symbol":      pos.symbol,
                "strategy":    pos.strategy,
                "entry_price": pos.entry_price,
                "ltp":         ltp,
                "stop_loss":   pos.stop_loss,
                "target":      pos.target,
                "unrealized":  round(unreal, 2),
                "quantity":    pos.quantity,
            })
        return result
