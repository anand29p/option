# utils/dhan_client.py
# ─────────────────────────────────────────────────────────────────────────────
# Dhan API Client — Free-tier replacement for Zerodha Kite Connect
#
# Setup (one-time):
#   1. Open account at dhan.co
#   2. Go to https://dhanhq.co/docs/v2/ → Get your Client ID + Access Token
#   3. Add to .env: DHAN_CLIENT_ID=... and DHAN_ACCESS_TOKEN=...
#
# No browser login flow needed! Token is long-lived (refreshed monthly).
# ─────────────────────────────────────────────────────────────────────────────

import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from dhanhq import DhanContext, dhanhq
from loguru import logger

from config.settings import DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN, IST

MAX_RETRIES = 4
RETRY_BASE  = 2   # seconds (exponential: 2, 4, 8, 16)


def _retry(fn, *args, retries=MAX_RETRIES, **kwargs):
    """Call fn with exponential backoff on failure."""
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            wait = RETRY_BASE ** attempt
            logger.warning(f"API call failed (attempt {attempt+1}/{retries}): {e} — retry in {wait}s")
            time.sleep(wait)
    logger.error(f"All {retries} retries exhausted for {fn}")
    return None


class DhanClient:
    """
    Dhan API wrapper (dhanhq v2.x).
    Drop-in replacement for KiteClient — same public interface.
    No browser login needed: just set DHAN_CLIENT_ID + DHAN_ACCESS_TOKEN in .env.
    Get credentials from: https://api.dhan.co
    """

    # Dhan security IDs (stable numeric identifiers for NSE indices)
    INDEX_SECURITY_IDS = {
        "NIFTY":     "13",
        "BANKNIFTY": "25",
        "FINNIFTY":  "27",
    }
    VIX_SECURITY_ID = "16084"

    # Exchange segment constants
    IDX_I   = "IDX_I"    # Index (Nifty spot, VIX)
    NSE_FNO = "NSE_FNO"  # NSE Futures & Options
    NSE_EQ  = "NSE_EQ"   # NSE Equity

    def __init__(self):
        if not DHAN_CLIENT_ID or not DHAN_ACCESS_TOKEN:
            raise ValueError(
                "\n❌ Missing Dhan credentials!\n"
                "   Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in your .env file.\n"
                "   Get them FREE at: https://api.dhan.co\n"
            )
        self._ctx  = DhanContext(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
        self._dhan = dhanhq(self._ctx)
        logger.info(f"✅ DhanClient ready (Client: {DHAN_CLIENT_ID})")

    # ── LTP / Quotes ──────────────────────────────────────────────────────────

    def get_ltp(self, security_ids: list[str], exchange: str = "NSE_FNO") -> dict[str, float]:
        """Returns {security_id: ltp} for given security IDs."""
        int_ids = [int(s) for s in security_ids]
        resp = _retry(self._dhan.ohlc_data, {exchange: int_ids})
        if not resp or resp.get("status") == "failure":
            return {}
        data = resp.get("data", {}).get(exchange, {})
        return {str(sid): float(v.get("last_price") or v.get("close", 0))
                for sid, v in data.items() if v.get("last_price") or v.get("close")}

    def get_spot_price(self, symbol: str, is_index: bool = True) -> Optional[float]:
        """Get current spot price for any index or stock.
        
        Args:
            symbol: Index (NIFTY, BANKNIFTY, FINNIFTY) or stock (TCS, INFY, etc.)
            is_index: If True, treats as index (IDX_I); if False, treats as stock (NSE_EQ)
        """
        from config.settings import SECURITY_IDS
        
        sid = SECURITY_IDS.get(symbol)
        if not sid:
            logger.warning(f"Security ID not found for {symbol}")
            return None
        
        exchange = self.IDX_I if is_index else self.NSE_EQ
        resp = _retry(self._dhan.ohlc_data, {exchange: [int(sid)]})
        if not resp or resp.get("status") == "failure":
            return None
        data = resp.get("data", {}).get(exchange, {})
        for v in data.values():
            return float(v.get("last_price") or v.get("close", 0))
        return None

    def get_vix(self) -> Optional[float]:
        """Fetch India VIX (used by StrategySelector)."""
        resp = _retry(self._dhan.ohlc_data, {self.IDX_I: [int(self.VIX_SECURITY_ID)]})
        if not resp or resp.get("status") == "failure":
            return None
        data = resp.get("data", {}).get(self.IDX_I, {})
        for v in data.values():
            return float(v.get("last_price") or v.get("close", 0))
        return None

    def get_quote(self, security_ids: list[str], exchange: str = "NSE_FNO") -> dict:
        """Full quote data including bid/ask/OI for options."""
        int_ids = [int(s) for s in security_ids]
        resp = _retry(self._dhan.ohlc_data, {exchange: int_ids})
        return resp or {}

    # ── Historical Data ───────────────────────────────────────────────────────

    def get_historical(
        self,
        security_id: str,
        interval: str = "minute",
        days_back: int = 1,
        exchange: str = "IDX_I",
        instrument_type: str = "INDEX",
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV candles as DataFrame.
        interval: minute | 5minute | 15minute | 60minute | day
        """
        from_dt = (datetime.now(IST) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        to_dt   = datetime.now(IST).strftime("%Y-%m-%d")

        if interval == "day":
            raw = _retry(self._dhan.historical_daily_data,
                         security_id, exchange, instrument_type, from_dt, to_dt)
        else:
            raw = _retry(self._dhan.intraday_minute_data,
                         security_id, exchange, instrument_type, from_dt, to_dt)

        df = self._parse_candles(raw)
        if df is None or df.empty:
            return None

        resample_map = {"5minute": "5min", "15minute": "15min", "60minute": "60min"}
        if interval in resample_map:
            df = self._resample(df, resample_map[interval])
        return df

    def get_historical_range(
        self,
        security_id: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "minute",
        exchange: str = "IDX_I",
        instrument_type: str = "INDEX",
    ) -> Optional[pd.DataFrame]:
        """Fetch historical data for an explicit date range (used by backtester)."""
        from_dt = from_date.strftime("%Y-%m-%d")
        to_dt   = to_date.strftime("%Y-%m-%d")
        if interval == "day":
            raw = _retry(self._dhan.historical_daily_data,
                         security_id, exchange, instrument_type, from_dt, to_dt)
        else:
            raw = _retry(self._dhan.intraday_minute_data,
                         security_id, exchange, instrument_type, from_dt, to_dt)

        df = self._parse_candles(raw)
        if df is None or df.empty:
            return None
        if interval == "5minute":
            df = self._resample(df, "5min")
        return df

    def _parse_candles(self, raw) -> Optional[pd.DataFrame]:
        """Convert Dhan historical response to OHLCV DataFrame indexed by IST datetime."""
        if not raw:
            return None
        data = raw if isinstance(raw, dict) else {}
        if "data" in data:
            data = data["data"]
            
        if not isinstance(data, dict):
            logger.error(f"Unexpected data format in historical data: {data}")
            return None

        closes  = data.get("close",      [])
        if not closes:
            return None

        opens   = data.get("open",       closes)
        highs   = data.get("high",       closes)
        lows    = data.get("low",        closes)
        volumes = data.get("volume",     [0] * len(closes))
        times   = data.get("start_Time", data.get("timestamp", []))

        if times:
            idx = pd.DatetimeIndex(
                [datetime.fromtimestamp(t, tz=IST) for t in times]
            )
        else:
            idx = pd.RangeIndex(len(closes))

        df = pd.DataFrame({
            "open": opens, "high": highs, "low": lows,
            "close": closes, "volume": volumes,
        }, index=idx)
        return df.astype(float)

    def _resample(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        return df.resample(rule).agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()

    # ── Option Chain ──────────────────────────────────────────────────────────

    def get_option_chain(self, symbol: str, expiry: str, is_index: bool = True) -> Optional[dict]:
        """Fetch full option chain for an index or stock on a given expiry date.
        
        Args:
            symbol: Index (NIFTY, BANKNIFTY, FINNIFTY) or stock (TCS, INFY, etc.)
            expiry: Expiry date string (YYYY-MM-DD)
            is_index: If True, treats as index (IDX_I); if False, treats as stock (NSE_FNO)
        """
        from config.settings import SECURITY_IDS
        
        sid = SECURITY_IDS.get(symbol)
        if not sid:
            logger.warning(f"Security ID not found for {symbol}")
            return None
        
        exchange = self.IDX_I if is_index else self.NSE_FNO
        resp = _retry(
            self._dhan.option_chain,
            under_security_id=int(sid),
            under_exchange_segment=exchange,
            expiry=expiry,
        )
        return resp

    def get_expiry_list(self, symbol: str, is_index: bool = True) -> list[str]:
        """Return list of upcoming expiry date strings for an index or stock.
        
        Args:
            symbol: Index (NIFTY, BANKNIFTY, FINNIFTY) or stock (TCS, INFY, etc.)
            is_index: If True, treats as index (IDX_I); if False, treats as stock (NSE_FNO)
        """
        from config.settings import SECURITY_IDS
        
        sid = SECURITY_IDS.get(symbol)
        if not sid:
            return []
        
        exchange = self.IDX_I if is_index else self.NSE_FNO
        resp = _retry(self._dhan.expiry_list,
                      under_security_id=int(sid),
                      under_exchange_segment=exchange)
        if not resp or resp.get("status") == "failure":
            return []
        return resp.get("data", {}).get("expiry_list", [])
