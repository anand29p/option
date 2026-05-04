# strategies/strategy_selector.py
# ─────────────────────────────────────────────────────────────────────────────
# Autonomous Strategy Selector
#
# Auto-selects and runs the best strategy every minute based on:
#   - India VIX level
#   - Time of day (session)
#   - Trend direction + strength
#   - Gap at open
#   - Recent performance (adaptive weight)
#
# NO human input ever needed. The bot decides everything.
# ─────────────────────────────────────────────────────────────────────────────

from datetime import datetime, time as dtime
from collections import defaultdict

import pandas as pd

from loguru import logger
from config.settings import (
    VIX_HIGH, VIX_MEDIUM, IST, INDICES,
    ACTIVE_STRATEGY_ALLOWLIST, SHADOW_SIGNAL_LOG,
)
from utils.shadow_journal import ShadowSignalJournal

from strategies.scalp_momentum      import ScalpMomentumStrategy
from strategies.orb_breakout        import ORBBreakoutStrategy
from strategies.mean_reversion      import MeanReversionStrategy
from strategies.vwap_reversion      import VWAPReversionStrategy
from strategies.supertrend_momentum import SuperTrendMomentumStrategy
from strategies.ema_crossover       import EMACrossoverStrategy
from strategies.gap_and_go          import GapAndGoStrategy
from strategies.rsi_divergence      import RSIDivergenceStrategy

import pandas_ta as ta


class StrategySelector:
    """
    Fully autonomous multi-strategy orchestrator.

    Every minute, for each index, it:
    1. Evaluates market regime (VIX, trend, session)
    2. Selects the highest-priority applicable strategies
    3. Generates signals from each
    4. Executes the first valid signal (priority ordered)

    Adaptive scoring: strategies that recently produced profitable
    trades get a small weight boost (±0.1 per win/loss).
    """

    # Sessions
    SESSION_OPEN   = (dtime(9, 15), dtime(9, 45))   # Gap + ORB window
    SESSION_MORNING = (dtime(9, 45), dtime(12, 0))   # High momentum
    SESSION_NOON    = (dtime(12, 0), dtime(14, 0))   # Often dead / rangebound
    SESSION_CLOSE   = (dtime(14, 0), dtime(15, 0))   # Afternoon trend + mean rev
    SESSION_CUTOFF  = dtime(15, 0)                   # No new entries after this

    def __init__(self, kite, paper_engine, risk_manager):
        self.kite    = kite
        self.engine  = paper_engine
        self.risk    = risk_manager

        # Instantiate all strategies
        self.scalp      = ScalpMomentumStrategy(kite, paper_engine)
        self.orb        = ORBBreakoutStrategy(kite, paper_engine)
        self.mr         = MeanReversionStrategy(kite, paper_engine)
        self.vwap_rev   = VWAPReversionStrategy(kite, paper_engine)
        self.supertrend = SuperTrendMomentumStrategy(kite, paper_engine)
        self.ema_cross  = EMACrossoverStrategy(kite, paper_engine)
        self.gap        = GapAndGoStrategy(kite, paper_engine)
        self.rsi_div    = RSIDivergenceStrategy(kite, paper_engine)

        # Adaptive performance scores (start neutral at 1.0)
        self._scores: dict[str, float] = defaultdict(lambda: 1.0)

        # Track last signal per index to avoid repeats
        self._last_signal: dict[str, str] = {}

        # Previous day closes for Gap strategy (fetched at pre_market)
        self._prev_closes: dict[str, float] = {}
        self._shadow = ShadowSignalJournal() if SHADOW_SIGNAL_LOG else None

        logger.info(
            "Active strategy allowlist: "
            + ", ".join(f"{idx}:{name}" for idx, name in sorted(ACTIVE_STRATEGY_ALLOWLIST))
        )

    # ── Day Reset ─────────────────────────────────────────────────────────────

    def reset_day(self):
        self.orb.reset_day()
        self.gap.reset_day()
        self.supertrend._last_dir.clear()
        self.ema_cross._last_cross.clear()
        self._last_signal.clear()
        logger.info("StrategySelector: day reset complete")

    def set_prev_closes(self, closes: dict[str, float]):
        """Called at pre-market with {index: prev_close}."""
        self._prev_closes = closes
        for idx, px in closes.items():
            self.gap.set_prev_close(idx, px)

    # ── Regime Detection ──────────────────────────────────────────────────────

    def _session(self) -> str:
        now = datetime.now(IST).time()
        if self.SESSION_OPEN[0] <= now <= self.SESSION_OPEN[1]:
            return "OPEN"
        if self.SESSION_MORNING[0] <= now < self.SESSION_MORNING[1]:
            return "MORNING"
        if self.SESSION_NOON[0] <= now < self.SESSION_NOON[1]:
            return "NOON"
        if self.SESSION_CLOSE[0] <= now < self.SESSION_CUTOFF:
            return "CLOSE"
        return "CLOSED"

    def _trend(self, df: pd.DataFrame) -> str:
        """UP | DOWN | SIDEWAYS using dual EMA slope."""
        if len(df) < 25:
            return "SIDEWAYS"
        fast = ta.ema(df["close"], length=9)
        slow = ta.ema(df["close"], length=21)
        if fast is None or slow is None:
            return "SIDEWAYS"
        slope = (fast.iloc[-1] - fast.iloc[-5]) / fast.iloc[-5] * 100
        if fast.iloc[-1] > slow.iloc[-1] and slope > 0.05:
            return "UP"
        if fast.iloc[-1] < slow.iloc[-1] and slope < -0.05:
            return "DOWN"
        return "SIDEWAYS"

    def _regime(self, vix: float, trend: str, session: str) -> str:
        """
        Returns regime string used to prioritize strategies.
        Regimes: HIGH_VOL_TREND | HIGH_VOL_SIDEWAYS |
                 MED_VOL_TREND  | LOW_VOL_SIDEWAYS
        """
        if vix >= VIX_HIGH and trend != "SIDEWAYS":
            return "HIGH_VOL_TREND"
        if vix >= VIX_HIGH:
            return "HIGH_VOL_SIDEWAYS"
        if vix >= VIX_MEDIUM and trend != "SIDEWAYS":
            return "MED_VOL_TREND"
        return "LOW_VOL_SIDEWAYS"

    # ── Strategy Priority Map ─────────────────────────────────────────────────

    def _get_priority_list(self, regime: str, session: str) -> list:
        """
        Returns ordered list of (strategy_obj, df_needed) tuples.
        First strategy with a valid signal wins per cycle.
        """
        # Each entry: (strategy, candle_df_key)
        # df_key: "1min" | "3min" | "5min"

        if session == "OPEN":
            return [
                (self.gap,        "1min"),   # Gap trade first
                (self.orb,        "1min"),   # Then ORB
                (self.scalp,      "1min"),   # Scalp if no gap/ORB
            ]

        if session == "CLOSED":
            return []

        if regime == "HIGH_VOL_TREND":
            return [
                (self.supertrend, "5min"),
                (self.ema_cross,  "3min"),
                (self.scalp,      "1min"),
                (self.vwap_rev,   "3min"),
            ]

        if regime == "HIGH_VOL_SIDEWAYS":
            return [
                (self.mr,         "5min"),
                (self.rsi_div,    "5min"),
                (self.vwap_rev,   "3min"),
            ]

        if regime == "MED_VOL_TREND":
            return [
                (self.ema_cross,  "3min"),
                (self.scalp,      "1min"),
                (self.supertrend, "5min"),
                (self.orb,        "1min"),
            ]

        # LOW_VOL_SIDEWAYS / NOON default
        if session == "NOON":
            return [
                (self.mr,       "5min"),
                (self.rsi_div,  "5min"),
            ]

        return [
            (self.mr,         "5min"),
            (self.vwap_rev,   "3min"),
            (self.rsi_div,    "5min"),
            (self.ema_cross,  "3min"),
        ]

    def _full_strategy_list(self, priority: list) -> list:
        """Priority list plus remaining strategies for shadow observation."""
        full = priority + [
            (self.gap,        "1min"),
            (self.orb,        "1min"),
            (self.scalp,      "1min"),
            (self.mr,         "5min"),
            (self.vwap_rev,   "3min"),
            (self.rsi_div,    "5min"),
            (self.supertrend, "5min"),
            (self.ema_cross,  "3min"),
        ]
        seen = set()
        unique = []
        for strat, df_key in full:
            if strat.NAME in seen:
                continue
            seen.add(strat.NAME)
            unique.append((strat, df_key))
        return unique

    @staticmethod
    def _is_active(index: str, strategy_name: str) -> bool:
        return (index, strategy_name) in ACTIVE_STRATEGY_ALLOWLIST

    def _record_shadow(
        self,
        index: str,
        strategy_name: str,
        signal: str,
        spot_price: float,
        session: str,
        regime: str,
        trend: str,
        vix: float,
        action: str,
        reason: str,
    ):
        if not self._shadow:
            return
        self._shadow.record(
            index=index,
            strategy=strategy_name,
            signal=signal,
            spot_price=spot_price,
            session=session,
            regime=regime,
            trend=trend,
            vix=vix,
            action=action,
            reason=reason,
        )

    # ── Main Cycle ────────────────────────────────────────────────────────────

    def run_cycle(
        self,
        index:       str,
        spot_price:  float,
        vix:         float,
        df_1min:     pd.DataFrame,
        df_5min:     pd.DataFrame,
    ):
        """
        Full autonomous cycle for one index. Called every minute.
        Selects regime → picks strategies → fires first valid signal.
        """
        session = self._session()
        if session == "CLOSED":
            return

        # Risk gate — don't even evaluate if trading is blocked
        ok, reason = self.engine.can_trade()
        if not ok:
            logger.debug(f"[{index}] Trading blocked: {reason}")
            return

        trend  = self._trend(df_1min)
        regime = self._regime(vix, trend, session)

        # Build 3-min candles by resampling 1-min
        df_3min = self._resample(df_1min, "3min")

        # ORB always gets its range updated regardless
        self.orb.update_orb(index, df_1min)

        priority = self._get_priority_list(regime, session)
        df_map   = {"1min": df_1min, "3min": df_3min, "5min": df_5min}

        for strat, df_key in self._full_strategy_list(priority):
            df = df_map.get(df_key, df_1min)

            try:
                # Special handling for strategies with different signatures
                if isinstance(strat, ORBBreakoutStrategy):
                    signal = strat.generate_signal(index, spot_price)
                elif isinstance(strat, GapAndGoStrategy):
                    signal = strat.generate_signal(index, spot_price)
                else:
                    signal = strat.generate_signal(index, df)
            except Exception as e:
                logger.error(f"[{index}] {strat.NAME} signal error: {e}")
                continue

            if signal == "NONE":
                continue

            # Suppress duplicate same-direction signals within 5 minutes
            last = self._last_signal.get(f"{index}:{strat.NAME}")
            if last == signal:
                logger.debug(f"[{index}] {strat.NAME}: duplicate signal suppressed")
                continue

            if not self._is_active(index, strat.NAME):
                logger.info(
                    f"SHADOW [{index}] {strat.NAME} -> {signal} | "
                    f"Session={session} Regime={regime} VIX={vix:.1f}"
                )
                self._record_shadow(
                    index=index,
                    strategy_name=strat.NAME,
                    signal=signal,
                    spot_price=spot_price,
                    session=session,
                    regime=regime,
                    trend=trend,
                    vix=vix,
                    action="shadow",
                    reason="not_in_active_allowlist",
                )
                self._last_signal[f"{index}:{strat.NAME}"] = signal
                continue

            logger.info(
                f"🎯 [{index}] {strat.NAME} → {signal} | "
                f"Session={session} Regime={regime} VIX={vix:.1f}"
            )

            try:
                strat.execute(index, signal, spot_price)
                self._last_signal[f"{index}:{strat.NAME}"] = signal
                self._record_shadow(
                    index=index,
                    strategy_name=strat.NAME,
                    signal=signal,
                    spot_price=spot_price,
                    session=session,
                    regime=regime,
                    trend=trend,
                    vix=vix,
                    action="executed",
                    reason="active_allowlist",
                )
            except Exception as e:
                logger.error(f"[{index}] {strat.NAME} execute error: {e}")

            break   # Only one strategy fires per cycle per index

    # ── Adaptive Score Update ─────────────────────────────────────────────────

    def update_score(self, strategy_name: str, won: bool):
        """Call after each trade close to adjust strategy weight."""
        delta = +0.1 if won else -0.05
        self._scores[strategy_name] = max(
            0.5, min(2.0, self._scores[strategy_name] + delta)
        )
        logger.debug(
            f"Score update: {strategy_name} → {self._scores[strategy_name]:.2f}"
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _resample(df: pd.DataFrame, freq: str) -> pd.DataFrame:
        """Resample 1-min OHLCV into a higher timeframe."""
        try:
            return df.resample(freq).agg({
                "open":   "first",
                "high":   "max",
                "low":    "min",
                "close":  "last",
                "volume": "sum",
            }).dropna()
        except Exception:
            return df
