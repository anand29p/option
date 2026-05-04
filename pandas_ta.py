"""Small local subset of pandas-ta used by this project.

The installed pandas_ta package hangs on import in the current environment, so
the bot uses these compatible indicator helpers for backtests and tests.
"""

from __future__ import annotations

import pandas as pd


def _series(values) -> pd.Series:
    return pd.Series(values, copy=False).astype(float)


def ema(close, length: int = 10) -> pd.Series:
    close = _series(close)
    return close.ewm(span=length, adjust=False, min_periods=length).mean()


def sma(close, length: int = 10) -> pd.Series:
    return _series(close).rolling(length, min_periods=length).mean()


def rsi(close, length: int = 14) -> pd.Series:
    close = _series(close)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def vwap(high, low, close, volume) -> pd.Series:
    high = _series(high)
    low = _series(low)
    close = _series(close)
    volume = _series(volume)
    typical = (high + low + close) / 3
    vol_sum = volume.cumsum().replace(0, pd.NA)
    return (typical * volume).cumsum() / vol_sum


def atr(high, low, close, length: int = 14) -> pd.Series:
    high = _series(high)
    low = _series(low)
    close = _series(close)
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


def bbands(close, length: int = 20, std: float = 2.0) -> pd.DataFrame:
    close = _series(close)
    mid = close.rolling(length, min_periods=length).mean()
    dev = close.rolling(length, min_periods=length).std(ddof=0)
    suffix = f"{length}_{float(std)}"
    return pd.DataFrame(
        {
            f"BBL_{suffix}": mid - float(std) * dev,
            f"BBM_{suffix}": mid,
            f"BBU_{suffix}": mid + float(std) * dev,
        },
        index=close.index,
    )


def supertrend(high, low, close, length: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    high = _series(high)
    low = _series(low)
    close = _series(close)
    hl2 = (high + low) / 2
    atr_values = atr(high, low, close, length=length)
    upper = hl2 + multiplier * atr_values
    lower = hl2 - multiplier * atr_values

    direction = pd.Series(1, index=close.index, dtype="int64")
    trend = pd.Series(pd.NA, index=close.index, dtype="float64")
    final_upper = upper.copy()
    final_lower = lower.copy()

    for i in range(1, len(close)):
        if pd.notna(final_upper.iloc[i - 1]):
            if upper.iloc[i] >= final_upper.iloc[i - 1] and close.iloc[i - 1] <= final_upper.iloc[i - 1]:
                final_upper.iloc[i] = final_upper.iloc[i - 1]
        if pd.notna(final_lower.iloc[i - 1]):
            if lower.iloc[i] <= final_lower.iloc[i - 1] and close.iloc[i - 1] >= final_lower.iloc[i - 1]:
                final_lower.iloc[i] = final_lower.iloc[i - 1]

        if close.iloc[i] > final_upper.iloc[i - 1]:
            direction.iloc[i] = 1
        elif close.iloc[i] < final_lower.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]

        trend.iloc[i] = final_lower.iloc[i] if direction.iloc[i] == 1 else final_upper.iloc[i]

    suffix = f"{length}_{float(multiplier)}"
    return pd.DataFrame(
        {
            f"SUPERT_{suffix}": trend,
            f"SUPERTd_{suffix}": direction,
        },
        index=close.index,
    )


def macd(close, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return pd.DataFrame(
        {
            f"MACD_{fast}_{slow}_{signal}": macd_line,
            f"MACDs_{fast}_{slow}_{signal}": signal_line,
            f"MACDh_{fast}_{slow}_{signal}": hist,
        },
        index=_series(close).index,
    )


def stoch(high, low, close, k: int = 14, d: int = 3, smooth_k: int = 3) -> pd.DataFrame:
    high = _series(high)
    low = _series(low)
    close = _series(close)
    lowest = low.rolling(k, min_periods=k).min()
    highest = high.rolling(k, min_periods=k).max()
    raw_k = 100 * (close - lowest) / (highest - lowest).replace(0, pd.NA)
    slow_k = raw_k.rolling(smooth_k, min_periods=smooth_k).mean()
    slow_d = slow_k.rolling(d, min_periods=d).mean()
    return pd.DataFrame(
        {
            f"STOCHk_{k}_{d}_{smooth_k}": slow_k,
            f"STOCHd_{k}_{d}_{smooth_k}": slow_d,
        },
        index=close.index,
    )
