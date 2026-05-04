# tests/test_strategies.py
# ─────────────────────────────────────────────────────────────────────────────
# Unit tests for strategy signal generation (no Kite API needed).
# Uses synthetic OHLCV data to validate signal logic.
# ─────────────────────────────────────────────────────────────────────────────

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


# ── Synthetic Data Helpers ────────────────────────────────────────────────────

def _make_df(n=100, trend="flat", base=22000.0) -> pd.DataFrame:
    """Create synthetic 1-min OHLCV DataFrame."""
    np.random.seed(42)
    prices = [base]

    for i in range(n - 1):
        if trend == "up":
            change = np.random.normal(5, 15)
        elif trend == "down":
            change = np.random.normal(-5, 15)
        else:
            change = np.random.normal(0, 10)
        prices.append(max(100, prices[-1] + change))

    start = datetime(2024, 6, 3, 9, 15, tzinfo=IST)
    index = [start + timedelta(minutes=i) for i in range(n)]
    closes = np.array(prices)

    return pd.DataFrame({
        "open":   closes * 0.999,
        "high":   closes * 1.002,
        "low":    closes * 0.998,
        "close":  closes,
        "volume": np.random.randint(50000, 200000, n).astype(float),
    }, index=pd.DatetimeIndex(index, tz=IST))


def _make_oversold_df(n=60, base=22000.0) -> pd.DataFrame:
    """Create data that drives RSI into oversold territory."""
    np.random.seed(1)
    prices = [base]
    for i in range(n - 1):
        if i < 40:
            prices.append(prices[-1] - abs(np.random.normal(8, 3)))  # Falling
        else:
            prices.append(prices[-1] + abs(np.random.normal(6, 2)))  # Recovering
    start = datetime(2024, 6, 3, 9, 15, tzinfo=IST)
    idx   = [start + timedelta(minutes=i) for i in range(n)]
    arr   = np.array(prices)
    return pd.DataFrame({
        "open": arr * 0.999, "high": arr * 1.002,
        "low": arr * 0.998,  "close": arr,
        "volume": np.random.randint(100000, 300000, n).astype(float),
    }, index=pd.DatetimeIndex(idx, tz=IST))


# ── Scalp Momentum ────────────────────────────────────────────────────────────

class TestScalpMomentum:
    def _make_strategy(self):
        from unittest.mock import MagicMock
        from strategies.scalp_momentum import ScalpMomentumStrategy
        kite   = MagicMock()
        engine = MagicMock()
        return ScalpMomentumStrategy(kite, engine)

    def test_returns_string(self):
        strat = self._make_strategy()
        df    = _make_df(60)
        sig   = strat.generate_signal("NIFTY", df)
        assert sig in ("BUY_CE", "BUY_PE", "NONE")

    def test_insufficient_data_returns_none(self):
        strat = self._make_strategy()
        df    = _make_df(5)
        assert strat.generate_signal("NIFTY", df) == "NONE"

    def test_no_crash_on_all_indices(self):
        strat = self._make_strategy()
        df    = _make_df(60)
        for idx in ["NIFTY", "BANKNIFTY", "FINNIFTY"]:
            result = strat.generate_signal(idx, df)
            assert result in ("BUY_CE", "BUY_PE", "NONE")

    def test_duplicate_signal_suppressed(self):
        strat = self._make_strategy()
        df    = _make_oversold_df(60)
        sig1  = strat.generate_signal("NIFTY", df)
        sig2  = strat.generate_signal("NIFTY", df)
        # If same signal, second should be NONE
        if sig1 != "NONE":
            assert sig2 == "NONE"


# ── ORB Breakout ──────────────────────────────────────────────────────────────

class TestORBBreakout:
    def _make_strategy(self):
        from unittest.mock import MagicMock
        from strategies.orb_breakout import ORBBreakoutStrategy
        return ORBBreakoutStrategy(MagicMock(), MagicMock())

    def test_no_signal_before_range_set(self):
        strat = self._make_strategy()
        assert strat.generate_signal("NIFTY", 22000) == "NONE"

    def test_breakout_above_high(self):
        strat = self._make_strategy()
        df    = _make_df(20)
        strat.update_orb("NIFTY", df)
        orb_high = df["high"].max()
        sig = strat.generate_signal("NIFTY", orb_high * 1.01)
        assert sig == "BUY_CE"

    def test_breakdown_below_low(self):
        strat = self._make_strategy()
        df    = _make_df(20)
        strat.update_orb("NIFTY", df)
        orb_low = df["low"].min()
        sig = strat.generate_signal("NIFTY", orb_low * 0.99)
        assert sig == "BUY_PE"

    def test_only_one_trade_per_day(self):
        strat = self._make_strategy()
        df    = _make_df(20)
        strat.update_orb("NIFTY", df)
        orb_high = df["high"].max()
        strat.traded.add("NIFTY")  # Simulate already traded
        sig = strat.generate_signal("NIFTY", orb_high * 1.01)
        assert sig == "NONE"

    def test_reset_day(self):
        strat = self._make_strategy()
        strat.traded.add("NIFTY")
        strat.reset_day()
        assert "NIFTY" not in strat.traded


# ── Mean Reversion ────────────────────────────────────────────────────────────

class TestMeanReversion:
    def _make_strategy(self):
        from unittest.mock import MagicMock
        from strategies.mean_reversion import MeanReversionStrategy
        return MeanReversionStrategy(MagicMock(), MagicMock())

    def test_returns_valid_signal(self):
        strat = self._make_strategy()
        df    = _make_df(60)
        sig   = strat.generate_signal("NIFTY", df)
        assert sig in ("BUY_CE", "BUY_PE", "NONE")

    def test_too_short_returns_none(self):
        strat = self._make_strategy()
        df    = _make_df(10)
        assert strat.generate_signal("NIFTY", df) == "NONE"


# ── EMA Crossover ─────────────────────────────────────────────────────────────

class TestEMACrossover:
    def _make_strategy(self):
        from unittest.mock import MagicMock
        from strategies.ema_crossover import EMACrossoverStrategy
        return EMACrossoverStrategy(MagicMock(), MagicMock())

    def test_signal_on_uptrend(self):
        strat = self._make_strategy()
        df    = _make_df(80, trend="up")
        sig   = strat.generate_signal("NIFTY", df)
        assert sig in ("BUY_CE", "BUY_PE", "NONE")

    def test_signal_on_downtrend(self):
        strat = self._make_strategy()
        df    = _make_df(80, trend="down")
        sig   = strat.generate_signal("NIFTY", df)
        assert sig in ("BUY_CE", "BUY_PE", "NONE")

    def test_no_crash_insufficient_data(self):
        strat = self._make_strategy()
        df    = _make_df(10)
        assert strat.generate_signal("NIFTY", df) == "NONE"


# ── RSI Divergence ────────────────────────────────────────────────────────────

class TestRSIDivergence:
    def _make_strategy(self):
        from unittest.mock import MagicMock
        from strategies.rsi_divergence import RSIDivergenceStrategy
        return RSIDivergenceStrategy(MagicMock(), MagicMock())

    def test_valid_signal(self):
        strat = self._make_strategy()
        df    = _make_df(60)
        sig   = strat.generate_signal("NIFTY", df)
        assert sig in ("BUY_CE", "BUY_PE", "NONE")


# ── Risk Manager ──────────────────────────────────────────────────────────────

class TestRiskManager:
    def _make_rm(self, daily_pnl=0, open_count=0, available=20000):
        from unittest.mock import MagicMock
        from utils.risk_manager import RiskManager
        engine = MagicMock()
        engine.daily_pnl = daily_pnl
        engine.open_trades = {f"T{i}": None for i in range(open_count)}
        engine.available_capital.return_value = available
        return RiskManager(engine)

    def test_trade_allowed_clean_state(self):
        rm = self._make_rm()
        ok, _ = rm.pre_trade_check(premium=100.0, quantity=25)
        assert ok

    def test_blocked_by_daily_loss(self):
        rm = self._make_rm(daily_pnl=-2500)
        ok, reason = rm.pre_trade_check(100.0, 25)
        assert not ok
        assert "loss" in reason.lower()

    def test_blocked_by_max_positions(self):
        rm = self._make_rm(open_count=2)
        ok, reason = rm.pre_trade_check(100.0, 25)
        assert not ok

    def test_blocked_by_capital(self):
        rm = self._make_rm(available=100)
        ok, reason = rm.pre_trade_check(premium=500.0, quantity=25)
        assert not ok

    def test_blocked_tiny_premium(self):
        rm = self._make_rm()
        ok, reason = rm.pre_trade_check(premium=3.0, quantity=25)
        assert not ok

    def test_position_sizing(self):
        rm = self._make_rm(available=20000)
        lots = rm.compute_position_size(premium=100.0, lot_size=25)
        assert lots >= 1

    def test_trailing_stop_breakeven(self):
        rm   = self._make_rm()
        sl   = rm.trailing_stop(entry_price=100, current_price=116)
        assert sl == pytest.approx(100.0)   # Breakeven

    def test_trailing_stop_lock_in(self):
        rm = self._make_rm()
        sl = rm.trailing_stop(entry_price=100, current_price=130)
        assert sl == pytest.approx(110.0)   # Lock in 10%
