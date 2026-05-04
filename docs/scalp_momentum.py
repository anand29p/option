# strategies/scalp_momentum.py
# ─────────────────────────────────────────────────────────────────────────────
# Scalp Momentum Strategy
# Timeframe: 1–3 minute candles
# Logic: RSI crossover + VWAP position + volume confirmation
# Target: 15–30% on option premium in quick 5–20 minute trades
# ─────────────────────────────────────────────────────────────────────────────

import pandas as pd
import pandas_ta as ta
from loguru import logger

from config.settings import (
    SCALP_RSI_PERIOD, SCALP_RSI_OVERBOUGHT, SCALP_RSI_OVERSOLD,
    SCALP_VWAP_BUFFER_PCT, MAX_CAPITAL_PER_TRADE, INDICES
)
from utils.option_chain import get_best_option
from utils.paper_engine import PaperEngine


class ScalpMomentumStrategy:
    """
    High-frequency scalp strategy based on:
    1. RSI momentum crossover (fast RSI 9-period)
    2. Price relative to VWAP (directional bias)
    3. Volume > 1.5× average (confirmation)

    Generates 3–8 signals per day per index during trending conditions.
    """

    NAME = "ScalpMomentum"

    def __init__(self, kite, paper_engine: PaperEngine):
        self.kite   = kite
        self.engine = paper_engine
        self.last_signal: dict[str, str] = {}   # index → last signal direction

    def generate_signal(self, index: str, df: pd.DataFrame) -> str:
        """
        Analyze 1-min OHLCV candles and return signal: BUY_CE | BUY_PE | NONE

        Args:
            index: NIFTY | BANKNIFTY | FINNIFTY
            df:    DataFrame with columns: open, high, low, close, volume, datetime
        """
        if len(df) < SCALP_RSI_PERIOD + 5:
            return "NONE"

        df = df.copy()

        # ── Indicators ────────────────────────────────────────────────────────
        df["rsi"]  = ta.rsi(df["close"], length=SCALP_RSI_PERIOD)
        df["vwap"] = ta.vwap(df["high"], df["low"], df["close"], df["volume"])
        df["vol_avg"] = df["volume"].rolling(20).mean()

        last   = df.iloc[-1]
        prev   = df.iloc[-2]
        signal = "NONE"

        rsi_now  = last["rsi"]
        rsi_prev = prev["rsi"]
        close    = last["close"]
        vwap     = last["vwap"]
        vol_ok   = last["volume"] > last["vol_avg"] * 1.5

        # Bullish: RSI rising from oversold zone + price above VWAP
        bullish = (
            rsi_prev < SCALP_RSI_OVERSOLD + 5 and
            rsi_now  > rsi_prev and
            close    > vwap * (1 + SCALP_VWAP_BUFFER_PCT) and
            vol_ok
        )

        # Bearish: RSI falling from overbought zone + price below VWAP
        bearish = (
            rsi_prev > SCALP_RSI_OVERBOUGHT - 5 and
            rsi_now  < rsi_prev and
            close    < vwap * (1 - SCALP_VWAP_BUFFER_PCT) and
            vol_ok
        )

        if bullish:
            signal = "BUY_CE"
        elif bearish:
            signal = "BUY_PE"

        # Avoid repeating same-direction signals back-to-back
        if signal != "NONE" and self.last_signal.get(index) == signal:
            logger.debug(f"[{index}] Skipping duplicate signal: {signal}")
            return "NONE"

        if signal != "NONE":
            logger.info(
                f"📡 [{index}] ScalpMomentum Signal: {signal} | "
                f"RSI={rsi_now:.1f} VWAP={vwap:.1f} Close={close:.1f}"
            )
            self.last_signal[index] = signal

        return signal

    def execute(self, index: str, signal: str, spot_price: float):
        """
        Execute a paper trade based on the generated signal.

        Args:
            index:       NIFTY | BANKNIFTY | FINNIFTY
            signal:      BUY_CE | BUY_PE
            spot_price:  Current index spot price
        """
        if signal == "NONE":
            return

        option_type = "CE" if signal == "BUY_CE" else "PE"
        idx_cfg     = INDICES[index]

        # Get best option: ATM or nearest ITM with good OI & tight spread
        option = get_best_option(
            kite        = self.kite,
            index       = index,
            spot_price  = spot_price,
            option_type = option_type,
            max_premium = MAX_CAPITAL_PER_TRADE / idx_cfg["lot_size"],
        )

        if option is None:
            logger.warning(f"[{index}] No suitable option found for {signal}")
            return

        # Determine affordable lots
        lots = max(1, int(MAX_CAPITAL_PER_TRADE / (option["ltp"] * idx_cfg["lot_size"])))
        lots = min(lots, 2)   # Cap at 2 lots per trade for scalping

        self.engine.enter_trade(
            symbol      = option["symbol"],
            index       = index,
            option_type = option_type,
            strike      = option["strike"],
            expiry      = option["expiry"],
            lots        = lots,
            lot_size    = idx_cfg["lot_size"],
            strategy    = self.NAME,
        )
