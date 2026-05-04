# strategies/strategy_selector.py
# ─────────────────────────────────────────────────────────────────────────────
# Auto Strategy Selector
# Picks the best strategy per session based on:
#   - India VIX level
#   - Time of day
#   - Recent market trend (slope of EMA)
# No manual intervention required.
# ─────────────────────────────────────────────────────────────────────────────

from datetime import datetime, time as dtime
import pandas as pd
import pandas_ta as ta
from loguru import logger
from zoneinfo import ZoneInfo

from config.settings import VIX_HIGH, VIX_MEDIUM, IST
from strategies.scalp_momentum import ScalpMomentumStrategy
from strategies.orb_breakout import ORBBreakoutStrategy
from strategies.mean_reversion import MeanReversionStrategy


class StrategySelector:
    """
    Autonomous strategy selector.
    Evaluates market conditions every cycle and routes signals
    to the appropriate strategy.
    """

    def __init__(self, kite, paper_engine):
        self.kite    = kite
        self.engine  = paper_engine

        # Instantiate all strategies
        self.scalp   = ScalpMomentumStrategy(kite, paper_engine)
        self.orb     = ORBBreakoutStrategy(kite, paper_engine)
        self.mr      = MeanReversionStrategy(kite, paper_engine)

        self._current_strategy = None

    def reset_day(self):
        """Call at market open to reset daily state."""
        self.orb.reset_day()
        self._current_strategy = None
        logger.info("StrategySelector: Day reset complete")

    def select(self, vix: float, df_1min: pd.DataFrame) -> str:
        """
        Determine which strategy to use.

        Args:
            vix:     Current India VIX value
            df_1min: Recent 1-min candles for trend detection

        Returns:
            Strategy name: "ScalpMomentum" | "ORBBreakout" | "MeanReversion"
        """
        now   = datetime.now(IST).time()
        trend = self._detect_trend(df_1min)

        # ── Time-based rules ──────────────────────────────────────────────────
        # First 30 minutes: always try ORB
        orb_window_start = dtime(9, 15)
        orb_window_end   = dtime(9, 45)

        if orb_window_start <= now <= orb_window_end:
            selected = "ORBBreakout"

        # After 3:00 PM: no new entries (approaching close)
        elif now >= dtime(15, 0):
            selected = "NONE"

        # ── VIX + Trend rules ──────────────────────────────────────────────────
        elif vix >= VIX_HIGH and trend != "SIDEWAYS":
            # High volatility + trending = scalp aggressively
            selected = "ScalpMomentum"

        elif VIX_MEDIUM <= vix < VIX_HIGH and trend != "SIDEWAYS":
            # Medium volatility + trending = scalp (safer)
            selected = "ScalpMomentum"

        elif vix < VIX_MEDIUM or trend == "SIDEWAYS":
            # Low volatility / sideways = mean reversion
            selected = "MeanReversion"

        else:
            selected = "ScalpMomentum"   # Default

        if selected != self._current_strategy:
            logger.info(
                f"📊 Strategy switched: {self._current_strategy} → {selected} "
                f"(VIX={vix:.1f}, Trend={trend}, Time={now})"
            )
            self._current_strategy = selected

        return selected

    def run_cycle(self, index: str, spot_price: float, vix: float,
                  df_1min: pd.DataFrame, df_5min: pd.DataFrame):
        """
        Full autonomous cycle: select strategy → generate signal → execute.

        Args:
            index:       NIFTY | BANKNIFTY | FINNIFTY
            spot_price:  Current index spot price
            vix:         India VIX
            df_1min:     1-minute OHLCV DataFrame
            df_5min:     5-minute OHLCV DataFrame
        """
        strategy_name = self.select(vix, df_1min)

        if strategy_name == "NONE":
            return

        if strategy_name == "ORBBreakout":
            self.orb.update_orb(index, df_1min)
            signal = self.orb.generate_signal(index, spot_price)
            self.orb.execute(index, signal, spot_price)

        elif strategy_name == "ScalpMomentum":
            signal = self.scalp.generate_signal(index, df_1min)
            self.scalp.execute(index, signal, spot_price)

        elif strategy_name == "MeanReversion":
            signal = self.mr.generate_signal(index, df_5min)
            self.mr.execute(index, signal, spot_price)

    # ── Internal: Trend Detection ─────────────────────────────────────────────

    def _detect_trend(self, df: pd.DataFrame) -> str:
        """
        Detect trend direction using EMA slope.

        Returns: "UP" | "DOWN" | "SIDEWAYS"
        """
        if len(df) < 20:
            return "SIDEWAYS"

        ema9  = ta.ema(df["close"], length=9)
        ema21 = ta.ema(df["close"], length=21)

        if ema9.iloc[-1] is None or ema21.iloc[-1] is None:
            return "SIDEWAYS"

        slope = (ema9.iloc[-1] - ema9.iloc[-5]) / ema9.iloc[-5] * 100

        if ema9.iloc[-1] > ema21.iloc[-1] and slope > 0.05:
            return "UP"
        elif ema9.iloc[-1] < ema21.iloc[-1] and slope < -0.05:
            return "DOWN"
        else:
            return "SIDEWAYS"
