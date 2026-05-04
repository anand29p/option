from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger

from config.settings import IST, LOG_DIR


class MarketDataRecorder:
    """Persist latest market candles each cycle for future backtesting."""

    def __init__(self, data_dir: Optional[str] = None):
        base = Path(data_dir) if data_dir else Path(LOG_DIR) / "market_data"
        base.mkdir(parents=True, exist_ok=True)
        self._data_dir = base
        self._last_ts: dict[str, datetime] = {}

    def record_cycle(
        self,
        index: str,
        spot_price: float,
        vix: float,
        df_1min: Optional[pd.DataFrame],
        df_5min: Optional[pd.DataFrame],
    ) -> None:
        """Save latest 1-min/5-min candle and a cycle snapshot row."""
        self._append_latest(index, "1min", df_1min)
        self._append_latest(index, "5min", df_5min)
        self._append_snapshot(index, spot_price, vix)

    def _append_latest(self, index: str, interval: str, df: Optional[pd.DataFrame]) -> None:
        if df is None or df.empty:
            return
        if not isinstance(df.index, pd.DatetimeIndex):
            return

        row = df.iloc[[-1]].copy()
        ts = row.index[-1].to_pydatetime()
        key = f"{index}:{interval}"
        if self._last_ts.get(key) == ts:
            return

        out = self._data_dir / f"{index}_{interval}.csv"
        write_header = not out.exists()

        row.insert(0, "timestamp", [ts.isoformat()])
        for col in ("open", "high", "low", "close", "volume"):
            if col not in row.columns:
                row[col] = 0.0

        row[["timestamp", "open", "high", "low", "close", "volume"]].to_csv(
            out,
            mode="a",
            index=False,
            header=write_header,
        )
        self._last_ts[key] = ts

    def _append_snapshot(self, index: str, spot_price: float, vix: float) -> None:
        out = self._data_dir / "cycle_snapshots.csv"
        write_header = not out.exists()
        now = datetime.now(IST).isoformat()

        with out.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(["timestamp", "index", "spot_price", "vix"])
            w.writerow([now, index, round(float(spot_price), 4), round(float(vix), 4)])


def load_recorded_ohlcv(index: str, days: int) -> Optional[pd.DataFrame]:
    """Load locally recorded 1-min candles for backtesting, if present."""
    path = Path(LOG_DIR) / "market_data" / f"{index}_1min.csv"
    if not path.exists():
        return None

    try:
        df = pd.read_csv(path, parse_dates=["timestamp"])
    except Exception as e:
        logger.warning(f"Failed to read recorded data for {index}: {e}")
        return None

    required = {"timestamp", "open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        return None

    if df.empty:
        return None

    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"]).copy()
    if df.empty:
        return None

    cutoff = datetime.now(IST) - timedelta(days=max(days, 1) + 1)
    df = df[df["timestamp"] >= cutoff]
    if df.empty:
        return None

    df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    df = df.set_index("timestamp")[["open", "high", "low", "close", "volume"]]
    return df.astype(float)
