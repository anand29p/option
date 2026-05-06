# strategies/opening_drive.py
# ─────────────────────────────────────────────────────────────────────────────
# Opening Drive Strategy
#
# Logic: Breakout from the first 30 minutes of trading (opening range breakout)
# Entry Window: After candle 30, until candle 120 (75 min)
# Setup: Price must break above/below 30-min high/low AND be above/below VWAP
# Best for: Morning range breakouts (9:45 AM onwards)
# Risk: Low selectivity due to wide opening range
# ─────────────────────────────────────────────────────────────────────────────

import pandas as pd
import pandas_ta as ta
from loguru import logger

from config.settings import MAX_CAPITAL_PER_TRADE, INDICES


class OpeningDriveStrategy:
    """
    Stricter opening range breakout after the first 30 candles.

    Entry Logic (5-min):
    1. During trading hours, after the first 30 candles (150 minutes)
    2. Entry window: candles 31-120 (until ~2:00 PM)
    3. Price must break above 30-min high × 1.001 AND be above VWAP
       → BUY_CE (bullish breakout)
    4. Or price breaks below 30-min low × 0.999 AND be below VWAP
       → BUY_PE (bearish breakout)
    5. Volume must exceed 1.25x average
    """

    NAME           = "OpeningDrive"
    LOOKBACK_BARS  = 30   # Number of bars for opening range
    MIN_ENTRY_BAR  = 31   # Start entering after bar 31
    MAX_ENTRY_BAR  = 120  # Stop entering after bar 120
    BREAKOUT_PCT   = 0.001  # 0.1% breakout threshold
    VOL_MULTIPLIER = 1.25

    def __init__(self, kite, paper_engine):
        self.kite   = kite
        self.engine = paper_engine

    def generate_signal(self, index: str, df: pd.DataFrame) -> str:
        """
        Generate signal: "BUY_CE", "BUY_PE", or "NONE"
        """
        if len(df) < self.MIN_ENTRY_BAR:
            return "NONE"

        # Determine which day we're in (375 bars per day for 5-min)
        current_bar = len(df) - 1
        day_start = current_bar - (current_bar % 375)
        bar_in_day = current_bar - day_start

        # Only trade during the opening window (bars 31-120)
        if bar_in_day < self.MIN_ENTRY_BAR or bar_in_day > self.MAX_ENTRY_BAR:
            return "NONE"

        # Get opening range (first 30 bars of the day)
        opening_start = day_start
        opening_end = min(day_start + self.LOOKBACK_BARS, current_bar)
        opening_window = df.iloc[opening_start:opening_end]

        if len(opening_window) < self.LOOKBACK_BARS:
            return "NONE"

        opening_high = opening_window["high"].max()
        opening_low = opening_window["low"].min()

        # Get current window for VWAP calculation
        window = df.iloc[max(day_start, current_bar - 35):current_bar + 1].copy()
        if len(window) < 20:
            return "NONE"

        window["vwap"] = ta.vwap(window["high"], window["low"], window["close"], window["volume"])
        window["vol_avg"] = window["volume"].rolling(20).mean()

        last = window.iloc[-1]
        last_close = float(last["close"])
        last_vwap = float(last["vwap"])
        vol_avg = float(last.get("vol_avg", 0) or 0)
        current_vol = float(last.get("volume", 0) or 0)

        # Check volume
        vol_ok = (vol_avg <= 0) or (current_vol > vol_avg * self.VOL_MULTIPLIER)
        if not vol_ok:
            return "NONE"

        # Bullish breakout: close above opening high AND above VWAP
        if last_close > opening_high * (1.0 + self.BREAKOUT_PCT) and last_close > last_vwap:
            logger.info(
                f"[{index}] Opening Drive Bullish: "
                f"breakout={opening_high:.2f} close={last_close:.2f} VWAP={last_vwap:.2f} → BUY_CE"
            )
            return "BUY_CE"

        # Bearish breakout: close below opening low AND below VWAP
        if last_close < opening_low * (1.0 - self.BREAKOUT_PCT) and last_close < last_vwap:
            logger.info(
                f"[{index}] Opening Drive Bearish: "
                f"breakout={opening_low:.2f} close={last_close:.2f} VWAP={last_vwap:.2f} → BUY_PE"
            )
            return "BUY_PE"

        return "NONE"

    def execute(self, index: str, signal: str, spot_price: float):
        """
        Execute the trade using paper_engine
        """
        if signal == "NONE":
            return

        from utils.option_chain import get_best_option

        cfg = INDICES[index]
        option_type = "CE" if signal == "BUY_CE" else "PE"

        option = get_best_option(
            kite=self.kite,
            index=index,
            spot_price=spot_price,
            option_type=option_type,
            max_premium=(MAX_CAPITAL_PER_TRADE * 0.8) / cfg["lot_size"],
        )

        if not option:
            logger.warning(f"[{index}] No suitable {option_type} option found")
            return

        lots = max(1, int((MAX_CAPITAL_PER_TRADE * 0.8) / (option["ltp"] * cfg["lot_size"])))

        self.engine.enter_trade(
            symbol=option["symbol"],
            index=index,
            option_type=option_type,
            strike=option["strike"],
            expiry=option["expiry"],
            lots=lots,
            lot_size=cfg["lot_size"],
            strategy=self.NAME,
        )
