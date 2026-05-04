# strategies/ema_crossover.py
# ─────────────────────────────────────────────────────────────────────────────
# EMA Crossover Strategy
# Logic: Fast EMA crosses Slow EMA with ATR volatility filter
# Timeframe: 3-min candles
# Best for: Trending sessions with moderate VIX (12–20)
# Target: 20–35% premium in 15–45 min
# ─────────────────────────────────────────────────────────────────────────────

import pandas as pd
import pandas_ta as ta
from loguru import logger

from config.settings import MAX_CAPITAL_PER_TRADE, INDICES


class EMACrossoverStrategy:
    """
    Classic EMA(9) × EMA(21) crossover with:
    - ATR filter: Only trade when ATR is above 20-period average (enough volatility)
    - No whipsaw: Minimum 3 candles since last crossover before new entry
    - VWAP alignment: Cross must happen on correct side of VWAP

    BUY_CE: EMA9 crosses above EMA21, price > VWAP, ATR elevated
    BUY_PE: EMA9 crosses below EMA21, price < VWAP, ATR elevated
    """

    NAME       = "EMACrossover"
    EMA_FAST   = 9
    EMA_SLOW   = 21
    ATR_PERIOD = 14

    def __init__(self, kite, paper_engine):
        self.kite         = kite
        self.engine       = paper_engine
        self._last_cross: dict[str, int] = {}   # index → candle index of last cross

    def generate_signal(self, index: str, df: pd.DataFrame) -> str:
        if len(df) < self.EMA_SLOW + 10:
            return "NONE"

        df = df.copy()
        df["ema_fast"] = ta.ema(df["close"], length=self.EMA_FAST)
        df["ema_slow"] = ta.ema(df["close"], length=self.EMA_SLOW)
        df["atr"]      = ta.atr(df["high"], df["low"], df["close"], length=self.ATR_PERIOD)
        df["atr_avg"]  = df["atr"].rolling(20).mean()
        df["vwap"]     = ta.vwap(df["high"], df["low"], df["close"], df["volume"])

        last = df.iloc[-1]
        prev = df.iloc[-2]

        atr_ok  = last["atr"] > last["atr_avg"] * 1.1   # Volatility is elevated
        n       = len(df)
        last_cx = self._last_cross.get(index, 0)
        cool    = (n - last_cx) >= 3   # At least 3 candles since last cross

        signal = "NONE"

        # Golden cross: fast crosses above slow
        if (prev["ema_fast"] <= prev["ema_slow"] and
                last["ema_fast"] > last["ema_slow"] and
                last["close"] > last["vwap"] and
                atr_ok and cool):
            signal = "BUY_CE"
            logger.info(f"[{index}] EMA Golden Cross → BUY_CE | ATR={last['atr']:.1f}")
            self._last_cross[index] = n

        # Death cross: fast crosses below slow
        elif (prev["ema_fast"] >= prev["ema_slow"] and
              last["ema_fast"] < last["ema_slow"] and
              last["close"] < last["vwap"] and
              atr_ok and cool):
            signal = "BUY_PE"
            logger.info(f"[{index}] EMA Death Cross → BUY_PE | ATR={last['atr']:.1f}")
            self._last_cross[index] = n

        return signal

    def execute(self, index: str, signal: str, spot_price: float):
        if signal == "NONE":
            return
        from utils.option_chain import get_best_option
        cfg = INDICES[index]
        option_type = "CE" if signal == "BUY_CE" else "PE"
        option = get_best_option(
            kite=self.kite, index=index, spot_price=spot_price,
            option_type=option_type,
            max_premium=MAX_CAPITAL_PER_TRADE / cfg["lot_size"],
        )
        if not option:
            return
        lots = max(1, int(MAX_CAPITAL_PER_TRADE / (option["ltp"] * cfg["lot_size"])))
        self.engine.enter_trade(
            symbol=option["symbol"], index=index, option_type=option_type,
            strike=option["strike"], expiry=option["expiry"],
            lots=lots, lot_size=cfg["lot_size"], strategy=self.NAME,
        )
