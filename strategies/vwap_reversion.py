# strategies/vwap_reversion.py
# ─────────────────────────────────────────────────────────────────────────────
# VWAP Reversion Strategy
# Logic: Price deviates >0.5% from VWAP → expect snap-back → buy option
# Best for: All VIX conditions, strong intraday trend with mean-pull
# Timeframe: 3-min candles
# Target: 15–25% premium in 10–30 min
# ─────────────────────────────────────────────────────────────────────────────

import pandas as pd
import pandas_ta as ta
from loguru import logger

from config.settings import MAX_CAPITAL_PER_TRADE, INDICES


class VWAPReversionStrategy:
    """
    If price is extended far from VWAP AND RSI is diverging,
    buy a near-ATM option in the reversion direction.

    Conditions for BUY_CE (expect bounce up):
      - Price > VWAP * 0.995 (slightly below VWAP)
      - Price recently touched VWAP band from below
      - RSI recovering from <40

    Conditions for BUY_PE (expect drop down):
      - Price < VWAP * 1.005 (slightly above VWAP)
      - Price recently touched VWAP band from above
      - RSI rolling over from >60
    """

    NAME = "VWAPReversion"
    VWAP_BAND = 0.005     # 0.5% deviation threshold
    RSI_PERIOD = 9

    def __init__(self, kite, paper_engine):
        self.kite   = kite
        self.engine = paper_engine

    def generate_signal(self, index: str, df: pd.DataFrame) -> str:
        if len(df) < 25:
            return "NONE"

        df = df.copy()
        df["vwap"] = ta.vwap(df["high"], df["low"], df["close"], df["volume"])
        df["rsi"]  = ta.rsi(df["close"], length=self.RSI_PERIOD)

        last = df.iloc[-1]
        prev = df.iloc[-2]
        close = last["close"]
        vwap  = last["vwap"]

        if vwap == 0 or pd.isna(vwap):
            return "NONE"

        dev = (close - vwap) / vwap

        # Price below VWAP and RSI recovering → expect bounce up → BUY CE
        if dev < -self.VWAP_BAND and last["rsi"] > prev["rsi"] and last["rsi"] < 45:
            logger.info(f"[{index}] VWAPRev: Price {dev:.2%} below VWAP → BUY_CE")
            return "BUY_CE"

        # Price above VWAP and RSI fading → expect drop → BUY PE
        if dev > self.VWAP_BAND and last["rsi"] < prev["rsi"] and last["rsi"] > 55:
            logger.info(f"[{index}] VWAPRev: Price {dev:.2%} above VWAP → BUY_PE")
            return "BUY_PE"

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
