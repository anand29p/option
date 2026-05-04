# utils/indicators.py
# ─────────────────────────────────────────────────────────────────────────────
# Technical Indicators
# Thin wrappers over pandas-ta for consistent usage across all strategies.
# All functions accept a DataFrame and return a Series or scalar.
# ─────────────────────────────────────────────────────────────────────────────

import pandas as pd
import pandas_ta as ta
from loguru import logger


def rsi(df: pd.DataFrame, period: int = 9) -> pd.Series:
    """RSI — Relative Strength Index."""
    return ta.rsi(df["close"], length=period)


def vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP — Volume Weighted Average Price (intraday, resets each day)."""
    return ta.vwap(df["high"], df["low"], df["close"], df["volume"])


def ema(df: pd.DataFrame, period: int = 21) -> pd.Series:
    """EMA — Exponential Moving Average."""
    return ta.ema(df["close"], length=period)


def sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """SMA — Simple Moving Average."""
    return ta.sma(df["close"], length=period)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR — Average True Range. Used for volatility-based stop placement."""
    return ta.atr(df["high"], df["low"], df["close"], length=period)


def bollinger_bands(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.DataFrame:
    """
    Bollinger Bands.
    Returns DataFrame with columns: BBL (lower), BBM (mid), BBU (upper), BBB (width %), BBP (percent).
    """
    return ta.bbands(df["close"], length=period, std=std)


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """
    SuperTrend indicator.
    Returns DataFrame with SUPERT (value) and SUPERTd (direction: 1=up, -1=down).
    """
    return ta.supertrend(df["high"], df["low"], df["close"], length=period, multiplier=multiplier)


def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD — Moving Average Convergence Divergence."""
    return ta.macd(df["close"], fast=fast, slow=slow, signal=signal)


def stochastic(df: pd.DataFrame, k: int = 14, d: int = 3, smooth_k: int = 3) -> pd.DataFrame:
    """Stochastic Oscillator."""
    return ta.stoch(df["high"], df["low"], df["close"], k=k, d=d, smooth_k=smooth_k)


def volume_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Volume ratio: current volume / rolling mean volume.
    Values > 1.5 indicate above-average volume (confirmation signal).
    """
    avg = df["volume"].rolling(period).mean()
    return df["volume"] / avg


def is_trending(df: pd.DataFrame, ema_fast: int = 9, ema_slow: int = 21, slope_threshold: float = 0.05) -> str:
    """
    Detect market trend using dual EMA and EMA slope.

    Returns: "UP" | "DOWN" | "SIDEWAYS"
    """
    if len(df) < ema_slow + 5:
        return "SIDEWAYS"

    fast = ta.ema(df["close"], length=ema_fast)
    slow = ta.ema(df["close"], length=ema_slow)

    if fast.iloc[-1] is None or slow.iloc[-1] is None:
        return "SIDEWAYS"

    slope_pct = (fast.iloc[-1] - fast.iloc[-5]) / fast.iloc[-5] * 100

    if fast.iloc[-1] > slow.iloc[-1] and slope_pct > slope_threshold:
        return "UP"
    elif fast.iloc[-1] < slow.iloc[-1] and slope_pct < -slope_threshold:
        return "DOWN"
    return "SIDEWAYS"


def pivot_points(df_prev_day: pd.DataFrame) -> dict:
    """
    Classic Pivot Points based on previous day's OHLC.
    Used for intraday support/resistance levels.

    Args:
        df_prev_day: DataFrame of previous day's candles

    Returns:
        dict with keys: PP, R1, R2, R3, S1, S2, S3
    """
    h = df_prev_day["high"].max()
    l = df_prev_day["low"].min()
    c = df_prev_day["close"].iloc[-1]

    pp = (h + l + c) / 3
    return {
        "PP": round(pp, 2),
        "R1": round(2 * pp - l, 2),
        "R2": round(pp + (h - l), 2),
        "R3": round(h + 2 * (pp - l), 2),
        "S1": round(2 * pp - h, 2),
        "S2": round(pp - (h - l), 2),
        "S3": round(l - 2 * (h - pp), 2),
    }
