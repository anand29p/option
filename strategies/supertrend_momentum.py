# strategies/supertrend_momentum.py
# ─────────────────────────────────────────────────────────────────────────────
# SuperTrend Momentum Strategy
# Logic: Trade in direction of SuperTrend flip with volume confirmation
# Timeframe: 5-min candles
# Best for: Clear trending days, VIX 14–22
# Target: 25–50% premium in 20–60 min (larger moves)
# ─────────────────────────────────────────────────────────────────────────────

import pandas as pd
import pandas_ta as ta
from loguru import logger

from config.settings import MAX_CAPITAL_PER_TRADE, INDICES


class SuperTrendMomentumStrategy:
    """
    Enters when SuperTrend flips direction on 5-min chart.
    Flip = strong momentum confirmation. Volume must be elevated.

    BUY_CE: SuperTrend flips from bearish→bullish (1) + volume spike
    BUY_PE: SuperTrend flips from bullish→bearish (-1) + volume spike
    """

    NAME       = "SuperTrendMomentum"
    ST_PERIOD  = 10
    ST_MULT    = 3.0
    VOL_MULT   = 1.8   # Volume must be 1.8× avg to confirm

    def __init__(self, kite, paper_engine):
        self.kite          = kite
        self.engine        = paper_engine
        self._last_dir: dict[str, int] = {}  # index → last supertrend direction

    def generate_signal(self, index: str, df: pd.DataFrame) -> str:
        if len(df) < self.ST_PERIOD + 5:
            return "NONE"

        df = df.copy()
        st = ta.supertrend(
            df["high"], df["low"], df["close"],
            length=self.ST_PERIOD, multiplier=self.ST_MULT
        )
        col_dir = f"SUPERTd_{self.ST_PERIOD}_{self.ST_MULT}"

        if col_dir not in st.columns:
            return "NONE"

        df["st_dir"]  = st[col_dir]
        df["vol_avg"] = df["volume"].rolling(20).mean()

        last = df.iloc[-1]
        prev = df.iloc[-2]

        cur_dir  = int(last["st_dir"])
        prev_dir = int(prev["st_dir"])
        vol_ok   = last["volume"] > last["vol_avg"] * self.VOL_MULT

        signal = "NONE"

        # Flip from -1 (bearish) to 1 (bullish)
        if prev_dir == -1 and cur_dir == 1 and vol_ok:
            signal = "BUY_CE"
            logger.info(f"[{index}] SuperTrend flip UP + vol={last['volume']:.0f} → BUY_CE")

        # Flip from 1 (bullish) to -1 (bearish)
        elif prev_dir == 1 and cur_dir == -1 and vol_ok:
            signal = "BUY_PE"
            logger.info(f"[{index}] SuperTrend flip DOWN + vol={last['volume']:.0f} → BUY_PE")

        # Avoid trading same direction twice in a row
        if signal != "NONE":
            last_signal = self._last_dir.get(index)
            if last_signal == signal:
                return "NONE"
            self._last_dir[index] = signal

        return signal

    def execute(self, index: str, signal: str, spot_price: float):
        if signal == "NONE":
            return
        from utils.option_chain import get_best_option
        cfg = INDICES[index]
        option_type = "CE" if signal == "BUY_CE" else "PE"
        # SuperTrend gets slightly ITM for stronger delta
        option = get_best_option(
            kite=self.kite, index=index, spot_price=spot_price,
            option_type=option_type,
            max_premium=MAX_CAPITAL_PER_TRADE / cfg["lot_size"],
            otm_offset=-1,  # 1 strike ITM — stronger delta for trend trades
        )
        if not option:
            return
        lots = max(1, int(MAX_CAPITAL_PER_TRADE / (option["ltp"] * cfg["lot_size"])))
        self.engine.enter_trade(
            symbol=option["symbol"], index=index, option_type=option_type,
            strike=option["strike"], expiry=option["expiry"],
            lots=lots, lot_size=cfg["lot_size"], strategy=self.NAME,
        )
