# strategies/rsi_divergence.py
# ─────────────────────────────────────────────────────────────────────────────
# RSI Divergence Strategy
# Logic: Price makes new high/low but RSI does NOT → reversal likely
# Timeframe: 5-min candles (looks back 10 candles)
# Best for: End of trend moves, exhaustion plays
# Target: 20–40% premium in 20–50 min
# ─────────────────────────────────────────────────────────────────────────────

import pandas as pd
import pandas_ta as ta
from loguru import logger

from config.settings import MAX_CAPITAL_PER_TRADE, INDICES


class RSIDivergenceStrategy:
    """
    Detects classic RSI divergence patterns:

    Bearish Divergence (BUY_PE):
      - Price: higher high in last N candles
      - RSI:   lower high (diverges downward)
      → Trend losing steam → short via PE

    Bullish Divergence (BUY_CE):
      - Price: lower low in last N candles
      - RSI:   higher low (diverges upward)
      → Selling exhausted → long via CE
    """

    NAME       = "RSIDivergence"
    RSI_PERIOD = 14
    LOOKBACK   = 10   # Candles to look back for divergence

    def __init__(self, kite, paper_engine):
        self.kite   = kite
        self.engine = paper_engine

    def generate_signal(self, index: str, df: pd.DataFrame) -> str:
        need = self.RSI_PERIOD + self.LOOKBACK + 2
        if len(df) < need:
            return "NONE"

        df = df.copy()
        df["rsi"] = ta.rsi(df["close"], length=self.RSI_PERIOD)
        df = df.dropna()

        recent = df.iloc[-self.LOOKBACK:]
        last   = df.iloc[-1]
        prev   = recent.iloc[:-1]

        price_hh = last["high"]  > prev["high"].max()
        price_ll = last["low"]   < prev["low"].min()
        rsi_hh   = last["rsi"]   > prev["rsi"].max()
        rsi_ll   = last["rsi"]   < prev["rsi"].min()

        # Bearish: price makes higher high but RSI doesn't
        if price_hh and not rsi_hh and last["rsi"] > 55:
            logger.info(
                f"[{index}] RSI Bearish Divergence: "
                f"price_HH={price_hh} rsi={last['rsi']:.1f} → BUY_PE"
            )
            return "BUY_PE"

        # Bullish: price makes lower low but RSI doesn't
        if price_ll and not rsi_ll and last["rsi"] < 45:
            logger.info(
                f"[{index}] RSI Bullish Divergence: "
                f"price_LL={price_ll} rsi={last['rsi']:.1f} → BUY_CE"
            )
            return "BUY_CE"

        return "NONE"

    def execute(self, index: str, signal: str, spot_price: float):
        if signal == "NONE":
            return
        from utils.option_chain import get_best_option
        cfg = INDICES[index]
        option_type = "CE" if signal == "BUY_CE" else "PE"
        option = get_best_option(
            kite=self.kite, index=index, spot_price=spot_price,
            option_type=option_type,
            max_premium=(MAX_CAPITAL_PER_TRADE * 0.8) / cfg["lot_size"],
        )
        if not option:
            return
        lots = max(1, int((MAX_CAPITAL_PER_TRADE * 0.8) / (option["ltp"] * cfg["lot_size"])))
        self.engine.enter_trade(
            symbol=option["symbol"], index=index, option_type=option_type,
            strike=option["strike"], expiry=option["expiry"],
            lots=lots, lot_size=cfg["lot_size"], strategy=self.NAME,
        )
