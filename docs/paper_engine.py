# utils/paper_engine.py
# ─────────────────────────────────────────────────────────────────────────────
# Paper Trade Execution Engine
# Simulates order fills using real-time Kite quotes.
# Maintains a virtual portfolio and tracks open/closed positions.
# ─────────────────────────────────────────────────────────────────────────────

import uuid
import csv
import json
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

from loguru import logger
from zoneinfo import ZoneInfo

from config.settings import (
    PAPER_CAPITAL, MAX_SIMULTANEOUS_TRADES, STOP_LOSS_PCT,
    TARGET_PCT_MIN, TARGET_PCT_MAX, MAX_DAILY_LOSS,
    LOG_DIR, TRADE_LOG, IST
)
from utils.tax_calculator import calculate_net_pnl, TradePnL

Path(LOG_DIR).mkdir(exist_ok=True)


@dataclass
class Position:
    """Represents one open paper trade position."""
    trade_id:       str
    symbol:         str          # e.g. "NIFTY24JUN22500CE"
    index:          str          # NIFTY | BANKNIFTY | FINNIFTY
    option_type:    str          # CE | PE
    strike:         int
    expiry:         str          # YYYY-MM-DD
    entry_price:    float        # Premium paid per unit
    quantity:       int          # lots × lot_size
    lots:           int
    entry_time:     datetime
    stop_loss:      float        # Absolute price level
    target:         float        # Absolute price level
    strategy:       str
    status:         str = "OPEN" # OPEN | CLOSED
    exit_price:     float = 0.0
    exit_time:      Optional[datetime] = None
    exit_reason:    str = ""
    pnl:            Optional[TradePnL] = field(default=None, repr=False)


class PaperEngine:
    """
    Fully autonomous paper trading engine.
    Maintains virtual capital, open positions, and a complete trade log.
    """

    def __init__(self, kite_client):
        self.kite         = kite_client
        self.capital      = PAPER_CAPITAL
        self.open_trades: dict[str, Position] = {}
        self.closed_trades: list[Position]    = []
        self.daily_pnl    = 0.0
        self._init_trade_log()
        logger.info(f"📋 Paper Engine initialized | Capital: ₹{self.capital:,.0f}")

    # ── Trade Log ─────────────────────────────────────────────────────────────

    def _init_trade_log(self):
        self.log_path = Path(TRADE_LOG)
        if not self.log_path.exists():
            with open(self.log_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "trade_id", "date", "symbol", "index", "option_type",
                    "strike", "expiry", "strategy", "lots", "quantity",
                    "entry_price", "entry_time", "exit_price", "exit_time",
                    "exit_reason", "gross_pnl", "total_charges", "net_pnl",
                    "net_pnl_pct", "stt", "brokerage", "gst",
                ])

    def _log_closed_trade(self, pos: Position):
        bd = pos.pnl.charge_breakdown if pos.pnl else {}
        with open(self.log_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                pos.trade_id,
                pos.entry_time.date(),
                pos.symbol,
                pos.index,
                pos.option_type,
                pos.strike,
                pos.expiry,
                pos.strategy,
                pos.lots,
                pos.quantity,
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

    # ── Capital Guard ──────────────────────────────────────────────────────────

    def can_trade(self) -> tuple[bool, str]:
        """Check if new trades are allowed."""
        if self.daily_pnl <= -MAX_DAILY_LOSS:
            return False, f"Daily loss limit hit (₹{self.daily_pnl:.0f})"
        if len(self.open_trades) >= MAX_SIMULTANEOUS_TRADES:
            return False, f"Max {MAX_SIMULTANEOUS_TRADES} simultaneous trades"
        return True, "OK"

    def available_capital(self) -> float:
        locked = sum(p.entry_price * p.quantity for p in self.open_trades.values())
        return max(0.0, self.capital - locked)

    # ── Entry ──────────────────────────────────────────────────────────────────

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
        """
        Simulate a market buy of an option.
        Returns the Position if successful, None otherwise.
        """
        ok, reason = self.can_trade()
        if not ok:
            logger.warning(f"⛔ Trade blocked: {reason}")
            return None

        # Fetch live LTP
        ltp = self._get_ltp(symbol)
        if ltp is None or ltp <= 0:
            logger.warning(f"⚠️  Could not fetch LTP for {symbol}")
            return None

        quantity    = lots * lot_size
        capital_req = ltp * quantity

        if capital_req > self.available_capital():
            logger.warning(
                f"⛔ Insufficient capital: need ₹{capital_req:.0f}, "
                f"available ₹{self.available_capital():.0f}"
            )
            return None

        stop_loss = round(ltp * (1 - STOP_LOSS_PCT), 2)
        target    = round(ltp * (1 + TARGET_PCT_MIN), 2)  # Conservative target

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
            stop_loss   = stop_loss,
            target      = target,
            strategy    = strategy,
        )

        self.open_trades[pos.trade_id] = pos
        logger.info(
            f"✅ ENTRY [{pos.trade_id}] {symbol} | LTP={ltp} | "
            f"Qty={quantity} | SL={stop_loss} | Target={target} | "
            f"Capital used=₹{capital_req:.0f}"
        )
        return pos

    # ── Exit ───────────────────────────────────────────────────────────────────

    def exit_trade(self, trade_id: str, reason: str = "manual") -> Optional[TradePnL]:
        """Exit an open position and calculate net P&L."""
        pos = self.open_trades.get(trade_id)
        if not pos:
            logger.error(f"Trade {trade_id} not found in open positions")
            return None

        ltp = self._get_ltp(pos.symbol)
        if ltp is None:
            ltp = pos.entry_price * 0.7   # Worst-case fallback
            logger.warning(f"Could not fetch LTP for exit, using fallback={ltp}")

        pos.exit_price  = ltp
        pos.exit_time   = datetime.now(IST)
        pos.exit_reason = reason
        pos.status      = "CLOSED"
        pos.pnl         = calculate_net_pnl(pos.entry_price, ltp, pos.quantity)

        net = pos.pnl.charge_breakdown["net_pnl"]
        self.daily_pnl += net

        del self.open_trades[trade_id]
        self.closed_trades.append(pos)
        self._log_closed_trade(pos)

        icon = "🟢" if net >= 0 else "🔴"
        logger.info(
            f"{icon} EXIT [{trade_id}] {pos.symbol} | "
            f"Entry={pos.entry_price} Exit={ltp} | "
            f"Net P&L=₹{net:.2f} | Reason={reason}"
        )
        return pos.pnl

    # ── Monitor Open Positions ─────────────────────────────────────────────────

    def monitor_positions(self):
        """
        Check all open positions against SL/Target.
        Called every minute by the scheduler.
        """
        for trade_id, pos in list(self.open_trades.items()):
            ltp = self._get_ltp(pos.symbol)
            if ltp is None:
                continue

            if ltp <= pos.stop_loss:
                self.exit_trade(trade_id, reason="stop_loss")
            elif ltp >= pos.target:
                self.exit_trade(trade_id, reason="target_hit")

    def squareoff_all(self):
        """Force exit all open positions (end of day)."""
        logger.info(f"🔔 Squaring off {len(self.open_trades)} open positions")
        for trade_id in list(self.open_trades.keys()):
            self.exit_trade(trade_id, reason="eod_squareoff")

    # ── LTP Fetch ─────────────────────────────────────────────────────────────

    def _get_ltp(self, symbol: str) -> Optional[float]:
        try:
            data = self.kite.ltp([f"NFO:{symbol}"])
            return data[f"NFO:{symbol}"]["last_price"]
        except Exception as e:
            logger.error(f"LTP fetch failed for {symbol}: {e}")
            return None

    # ── Portfolio Status ───────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "capital":           round(self.capital, 2),
            "available_capital": round(self.available_capital(), 2),
            "open_positions":    len(self.open_trades),
            "daily_pnl":         round(self.daily_pnl, 2),
            "total_trades":      len(self.closed_trades),
        }
