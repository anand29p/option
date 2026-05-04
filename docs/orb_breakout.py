# strategies/orb_breakout.py
# ─────────────────────────────────────────────────────────────────────────────
# Opening Range Breakout (ORB) Strategy
# Timeframe: 15-minute opening range (9:15–9:30 AM)
# Logic: Buy CE on breakout above range high, Buy PE on breakdown below range low
# Target: 20–40% premium gain on strong trend days
# ─────────────────────────────────────────────────────────────────────────────

import pandas as pd
from datetime import time as dtime
from loguru import logger
from zoneinfo import ZoneInfo

from config.settings import (
    ORB_MINUTES, ORB_BUFFER_PCT, MAX_CAPITAL_PER_TRADE, INDICES, IST
)
from utils.option_chain import get_best_option
from utils.paper_engine import PaperEngine


class ORBBreakoutStrategy:
    """
    Opening Range Breakout:
    - Observes first ORB_MINUTES (default 15) of trading
    - Stores the high and low of that range
    - Triggers on clean breakout above/below range
    - Trades only ONCE per index per day (high conviction, single entry)
    """

    NAME = "ORBBreakout"

    def __init__(self, kite, paper_engine: PaperEngine):
        self.kite       = kite
        self.engine     = paper_engine
        self.orb: dict  = {}      # index → {high, low, set}
        self.traded: set = set()  # indices already traded today

    def reset_day(self):
        """Call at market open each day."""
        self.orb    = {}
        self.traded = set()
        logger.info("ORB: Day reset — ranges cleared")

    def update_orb(self, index: str, df: pd.DataFrame):
        """
        Build the opening range from 1-min candles during 9:15–9:30.

        Args:
            df: 1-min OHLCV candles with datetime index (IST-aware)
        """
        orb_end = dtime(9, 15 + ORB_MINUTES)
        opening = df[df.index.time < orb_end]

        if len(opening) < ORB_MINUTES:
            return   # Range not complete yet

        self.orb[index] = {
            "high": opening["high"].max(),
            "low":  opening["low"].min(),
            "set":  True,
        }
        logger.info(
            f"[{index}] ORB Range set: "
            f"High={self.orb[index]['high']:.1f} "
            f"Low={self.orb[index]['low']:.1f}"
        )

    def generate_signal(self, index: str, current_price: float) -> str:
        """
        Check if price has broken out of the ORB range.

        Returns: BUY_CE | BUY_PE | NONE
        """
        if index in self.traded:
            return "NONE"

        orb = self.orb.get(index)
        if not orb or not orb.get("set"):
            return "NONE"

        buf_high = orb["high"] * (1 + ORB_BUFFER_PCT)
        buf_low  = orb["low"]  * (1 - ORB_BUFFER_PCT)

        if current_price > buf_high:
            logger.info(f"[{index}] ORB Breakout UP: {current_price:.1f} > {buf_high:.1f}")
            return "BUY_CE"
        elif current_price < buf_low:
            logger.info(f"[{index}] ORB Breakdown DOWN: {current_price:.1f} < {buf_low:.1f}")
            return "BUY_PE"

        return "NONE"

    def execute(self, index: str, signal: str, spot_price: float):
        """Execute paper trade on ORB breakout signal."""
        if signal == "NONE" or index in self.traded:
            return

        option_type = "CE" if signal == "BUY_CE" else "PE"
        idx_cfg     = INDICES[index]

        option = get_best_option(
            kite        = self.kite,
            index       = index,
            spot_price  = spot_price,
            option_type = option_type,
            max_premium = MAX_CAPITAL_PER_TRADE / idx_cfg["lot_size"],
        )

        if option is None:
            logger.warning(f"[{index}] ORB: No suitable option found")
            return

        lots = max(1, int(MAX_CAPITAL_PER_TRADE / (option["ltp"] * idx_cfg["lot_size"])))

        pos = self.engine.enter_trade(
            symbol      = option["symbol"],
            index       = index,
            option_type = option_type,
            strike      = option["strike"],
            expiry      = option["expiry"],
            lots        = lots,
            lot_size    = idx_cfg["lot_size"],
            strategy    = self.NAME,
        )

        if pos:
            self.traded.add(index)   # Only one ORB trade per index per day
