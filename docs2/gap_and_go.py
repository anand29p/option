# strategies/gap_and_go.py
# ─────────────────────────────────────────────────────────────────────────────
# Gap and Go Strategy
# Logic: Index opens with a significant gap → trade in gap direction
# Timeframe: First 5 minutes (9:15–9:20)
# Best for: High VIX days, news-driven gaps (budget, RBI, global events)
# Target: 40–80% premium in 15–60 min (high reward, single trade per day)
# ─────────────────────────────────────────────────────────────────────────────

import pandas as pd
from datetime import datetime, time as dtime
from loguru import logger

from config.settings import MAX_CAPITAL_PER_TRADE, INDICES, IST


class GapAndGoStrategy:
    """
    Detects opening gap > GAP_THRESHOLD% from previous close.
    Buys option in gap direction immediately at open.
    Only ONE trade per index per day.

    Gap Up  → BUY_CE (momentum continuation expected)
    Gap Down → BUY_PE (momentum continuation expected)
    """

    NAME          = "GapAndGo"
    GAP_THRESHOLD = 0.004   # 0.4% gap required
    FIRE_WINDOW   = dtime(9, 15), dtime(9, 25)   # Only fire in first 10 min

    def __init__(self, kite, paper_engine):
        self.kite       = kite
        self.engine     = paper_engine
        self._prev_close: dict[str, float] = {}
        self._traded: set[str] = set()

    def reset_day(self):
        self._prev_close = {}
        self._traded     = set()

    def set_prev_close(self, index: str, prev_close: float):
        """Call before market open with previous day's close."""
        self._prev_close[index] = prev_close
        logger.info(f"[{index}] Gap strategy: prev_close=₹{prev_close:.1f}")

    def generate_signal(self, index: str, current_price: float) -> str:
        now = datetime.now(IST).time()
        if not (self.FIRE_WINDOW[0] <= now <= self.FIRE_WINDOW[1]):
            return "NONE"
        if index in self._traded:
            return "NONE"
        if index not in self._prev_close:
            return "NONE"

        prev   = self._prev_close[index]
        gap    = (current_price - prev) / prev

        if gap > self.GAP_THRESHOLD:
            logger.info(f"[{index}] GAP UP {gap:.2%} → BUY_CE")
            return "BUY_CE"
        elif gap < -self.GAP_THRESHOLD:
            logger.info(f"[{index}] GAP DOWN {gap:.2%} → BUY_PE")
            return "BUY_PE"

        return "NONE"

    def execute(self, index: str, signal: str, spot_price: float):
        if signal == "NONE" or index in self._traded:
            return
        from utils.option_chain import get_best_option
        cfg = INDICES[index]
        option_type = "CE" if signal == "BUY_CE" else "PE"
        # For gap trades buy slightly OTM — cheaper and gap has momentum
        option = get_best_option(
            kite=self.kite, index=index, spot_price=spot_price,
            option_type=option_type,
            max_premium=MAX_CAPITAL_PER_TRADE / cfg["lot_size"],
            otm_offset=1,
        )
        if not option:
            return
        lots = max(1, int(MAX_CAPITAL_PER_TRADE / (option["ltp"] * cfg["lot_size"])))
        pos = self.engine.enter_trade(
            symbol=option["symbol"], index=index, option_type=option_type,
            strike=option["strike"], expiry=option["expiry"],
            lots=lots, lot_size=cfg["lot_size"], strategy=self.NAME,
        )
        if pos:
            self._traded.add(index)
