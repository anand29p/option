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
        option_chain: Optional[dict] = None,
        option_expiry: str = "",
        strike_step: int = 50,
        strike_span: int = 4,
    ) -> None:
        """Save latest 1-min/5-min candle and a cycle snapshot row."""
        self._append_latest(index, "1min", df_1min)
        self._append_latest(index, "5min", df_5min)
        self._append_snapshot(index, spot_price, vix)
        if option_chain:
            self._append_option_chain(
                index=index,
                expiry=option_expiry,
                spot_price=spot_price,
                chain_data=option_chain,
                strike_step=max(int(strike_step), 1),
                strike_span=max(int(strike_span), 0),
            )

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

    @staticmethod
    def _to_float(value: object, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except Exception:
            return default

    def _append_option_chain(
        self,
        index: str,
        expiry: str,
        spot_price: float,
        chain_data: dict,
        strike_step: int,
        strike_span: int,
    ) -> None:
        """Persist near-ATM option chain rows plus ATM CE/PE snapshot for backtests."""
        if not isinstance(chain_data, dict) or not chain_data:
            return

        now = datetime.now(IST).isoformat()
        atm_strike = int(round(float(spot_price) / strike_step) * strike_step)

        long_out = self._data_dir / f"{index}_options_near_atm.csv"
        long_header = not long_out.exists()
        atm_out = self._data_dir / f"{index}_options_atm.csv"
        atm_header = not atm_out.exists()

        ce_atm_ltp = 0.0
        pe_atm_ltp = 0.0
        ce_atm_oi = 0
        pe_atm_oi = 0
        ce_atm_sid = ""
        pe_atm_sid = ""

        rows: list[list[object]] = []
        min_strike = atm_strike - strike_span * strike_step
        max_strike = atm_strike + strike_span * strike_step

        for strike_key, strike_payload in chain_data.items():
            try:
                strike = int(float(strike_key))
            except Exception:
                continue

            if strike < min_strike or strike > max_strike:
                continue

            for option_type, side_key in (("CE", "call_options"), ("PE", "put_options")):
                side = (strike_payload or {}).get(side_key, {})
                if not isinstance(side, dict) or not side:
                    continue

                market = side.get("market_data", {}) or {}
                meta = side.get("option_data", {}) or {}
                ltp = self._to_float(market.get("ltp", market.get("last_price", 0.0)), 0.0)
                if ltp <= 0:
                    continue

                bid = self._to_float(market.get("bid_price", 0.0), 0.0)
                ask = self._to_float(market.get("ask_price", 0.0), 0.0)
                oi = int(self._to_float(market.get("oi", 0), 0.0))
                iv = self._to_float(market.get("implied_volatility", 0.0), 0.0)
                volume = int(self._to_float(market.get("volume", 0), 0.0))
                security_id = str(meta.get("security_id", "") or "")

                rows.append([
                    now,
                    index,
                    expiry,
                    round(float(spot_price), 4),
                    atm_strike,
                    strike,
                    option_type,
                    round(ltp, 4),
                    round(bid, 4),
                    round(ask, 4),
                    oi,
                    round(iv, 6),
                    volume,
                    security_id,
                ])

                if strike == atm_strike:
                    if option_type == "CE":
                        ce_atm_ltp = ltp
                        ce_atm_oi = oi
                        ce_atm_sid = security_id
                    else:
                        pe_atm_ltp = ltp
                        pe_atm_oi = oi
                        pe_atm_sid = security_id

        if rows:
            with long_out.open("a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if long_header:
                    w.writerow([
                        "timestamp",
                        "index",
                        "expiry",
                        "spot_price",
                        "atm_strike",
                        "strike",
                        "option_type",
                        "ltp",
                        "bid",
                        "ask",
                        "oi",
                        "iv",
                        "volume",
                        "security_id",
                    ])
                w.writerows(rows)

        if ce_atm_ltp > 0 or pe_atm_ltp > 0:
            with atm_out.open("a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if atm_header:
                    w.writerow([
                        "timestamp",
                        "index",
                        "expiry",
                        "spot_price",
                        "atm_strike",
                        "ce_ltp",
                        "pe_ltp",
                        "ce_oi",
                        "pe_oi",
                        "ce_security_id",
                        "pe_security_id",
                    ])
                w.writerow([
                    now,
                    index,
                    expiry,
                    round(float(spot_price), 4),
                    atm_strike,
                    round(ce_atm_ltp, 4),
                    round(pe_atm_ltp, 4),
                    ce_atm_oi,
                    pe_atm_oi,
                    ce_atm_sid,
                    pe_atm_sid,
                ])


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


def load_recorded_atm_options(index: str, days: int) -> Optional[pd.DataFrame]:
    """Load recorded ATM CE/PE premium snapshots for an index."""
    path = Path(LOG_DIR) / "market_data" / f"{index}_options_atm.csv"
    if not path.exists():
        return None

    try:
        df = pd.read_csv(path, parse_dates=["timestamp"])
    except Exception as e:
        logger.warning(f"Failed to read recorded ATM options for {index}: {e}")
        return None

    required = {"timestamp", "ce_ltp", "pe_ltp", "spot_price", "atm_strike"}
    if not required.issubset(df.columns):
        return None

    if df.empty:
        return None

    cutoff = datetime.now(IST) - timedelta(days=max(days, 1) + 1)
    df = df[df["timestamp"] >= cutoff]
    if df.empty:
        return None

    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    df = df.drop_duplicates(subset=["timestamp"], keep="last")

    for col in ("ce_ltp", "pe_ltp", "spot_price", "atm_strike"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["spot_price", "atm_strike"])
    if df.empty:
        return None

    return df.set_index("timestamp")
