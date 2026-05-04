# utils/risk_manager.py
# ─────────────────────────────────────────────────────────────────────────────
# Risk Manager
# Central guard for all pre-trade and post-trade risk checks.
# Called before every entry attempt and after every exit.
# ─────────────────────────────────────────────────────────────────────────────

from loguru import logger
from config.settings import (
    MAX_CAPITAL_PER_TRADE, MAX_SIMULTANEOUS_TRADES,
    MAX_DAILY_LOSS, STOP_LOSS_PCT, TARGET_PCT_MIN, PAPER_CAPITAL
)


class RiskManager:
    """
    Enforces all risk rules. Returns (allowed: bool, reason: str).
    """

    def __init__(self, paper_engine):
        self.engine = paper_engine

    def pre_trade_check(self, premium: float, quantity: int) -> tuple[bool, str]:
        """
        Run all checks before entering a trade.

        Checks:
        1. Daily loss limit not breached
        2. Max simultaneous positions not exceeded
        3. Capital per trade within limit
        4. Sufficient available capital
        5. Minimum premium sanity (not < ₹5)
        """
        capital_req = premium * quantity

        # 1. Daily loss limit
        if self.engine.daily_pnl <= -MAX_DAILY_LOSS:
            return False, f"Daily loss limit reached: ₹{self.engine.daily_pnl:.0f}"

        # 2. Max positions
        if len(self.engine.open_trades) >= MAX_SIMULTANEOUS_TRADES:
            return False, f"Max {MAX_SIMULTANEOUS_TRADES} open positions already"

        # 3. Capital per trade
        if capital_req > MAX_CAPITAL_PER_TRADE:
            return False, f"Trade cost ₹{capital_req:.0f} exceeds max ₹{MAX_CAPITAL_PER_TRADE}"

        # 4. Available capital
        if capital_req > self.engine.available_capital():
            return False, f"Insufficient capital: need ₹{capital_req:.0f}, have ₹{self.engine.available_capital():.0f}"

        # 5. Premium sanity
        if premium < 5:
            return False, f"Premium ₹{premium} too low — likely illiquid"

        return True, "OK"

    def compute_position_size(self, premium: float, lot_size: int) -> int:
        """
        Return number of lots to buy given premium and lot size.
        Stays within MAX_CAPITAL_PER_TRADE and available capital.
        """
        max_lots_by_limit    = int(MAX_CAPITAL_PER_TRADE / (premium * lot_size))
        max_lots_by_capital  = int(self.engine.available_capital() / (premium * lot_size))
        lots = min(max_lots_by_limit, max_lots_by_capital)
        lots = max(1, lots)  # At least 1 lot
        return lots

    def trailing_stop(self, entry_price: float, current_price: float) -> float:
        """
        Compute a simple trailing stop level.
        Once in profit > 15%, trail stop to breakeven.
        Once in profit > 25%, trail stop to +10%.
        """
        gain_pct = (current_price - entry_price) / entry_price

        if gain_pct >= 0.25:
            return entry_price * 1.10  # Lock in 10%
        elif gain_pct >= 0.15:
            return entry_price * 1.00  # Breakeven
        else:
            return entry_price * (1 - STOP_LOSS_PCT)  # Normal SL

    def portfolio_heat(self) -> float:
        """
        Returns what % of total capital is currently at risk.
        (Sum of stop-loss exposure across all open trades)
        """
        total_at_risk = 0.0
        for pos in self.engine.open_trades.values():
            worst_case_loss = (pos.entry_price - pos.stop_loss) * pos.quantity
            total_at_risk += max(0, worst_case_loss)
        return round(total_at_risk / PAPER_CAPITAL * 100, 2)

    def log_risk_status(self):
        status = self.engine.status()
        heat   = self.portfolio_heat()
        logger.info(
            f"🛡️  Risk | DayP&L=₹{status['daily_pnl']:.0f} | "
            f"OpenPos={status['open_positions']} | "
            f"Heat={heat}% | Available=₹{status['available_capital']:.0f}"
        )
