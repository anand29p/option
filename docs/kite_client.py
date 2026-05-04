# utils/kite_client.py
# ─────────────────────────────────────────────────────────────────────────────
# Zerodha Kite Connect API wrapper.
# Handles login, token caching, historical data, LTP, and option chain.
# ─────────────────────────────────────────────────────────────────────────────

import os
import json
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from kiteconnect import KiteConnect
from loguru import logger

from config.settings import KITE_API_KEY, KITE_API_SECRET, KITE_TOKEN_FILE, IST


class KiteClient:
    """
    Thin wrapper around kiteconnect.KiteConnect.
    Handles:
    - One-time browser-based login per day
    - Access token caching (file-based, reloaded on startup)
    - Historical candle data (1min, 5min, etc.)
    - LTP and quote fetching
    - India VIX fetching
    """

    VIX_SYMBOL = "NSE:INDIA VIX"

    def __init__(self):
        self.kite = KiteConnect(api_key=KITE_API_KEY)
        self._load_or_login()

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _load_or_login(self):
        token_path = Path(KITE_TOKEN_FILE)

        if token_path.exists():
            data = json.loads(token_path.read_text())
            saved_date = data.get("date")
            token      = data.get("access_token")
            today      = datetime.now(IST).strftime("%Y-%m-%d")

            if saved_date == today and token:
                self.kite.set_access_token(token)
                logger.info(f"✅ Kite: loaded cached access token for {today}")
                return

        self._do_login()

    def _do_login(self):
        """Open browser for Zerodha login and save access token."""
        login_url = self.kite.login_url()
        logger.info(f"🌐 Opening browser for Zerodha login...")
        webbrowser.open(login_url)

        request_token = input(
            "\nPaste the 'request_token' from the redirect URL and press Enter: "
        ).strip()

        session = self.kite.generate_session(request_token, api_secret=KITE_API_SECRET)
        access_token = session["access_token"]
        self.kite.set_access_token(access_token)

        # Cache token with today's date
        Path(KITE_TOKEN_FILE).write_text(json.dumps({
            "date":         datetime.now(IST).strftime("%Y-%m-%d"),
            "access_token": access_token,
        }))
        logger.info("✅ Kite: Login successful. Token cached.")

    # ── Market Data ───────────────────────────────────────────────────────────

    def get_ltp(self, instruments: list[str]) -> dict:
        """
        Fetch Last Traded Price for a list of instrument symbols.

        Args:
            instruments: e.g. ["NSE:NIFTY 50", "NFO:NIFTY24JUN22500CE"]

        Returns:
            Dict mapping symbol → last_price
        """
        try:
            data = self.kite.ltp(instruments)
            return {k: v["last_price"] for k, v in data.items()}
        except Exception as e:
            logger.error(f"LTP fetch error: {e}")
            return {}

    def get_vix(self) -> Optional[float]:
        """Fetch current India VIX value."""
        try:
            data = self.kite.ltp([self.VIX_SYMBOL])
            return data[self.VIX_SYMBOL]["last_price"]
        except Exception as e:
            logger.error(f"VIX fetch error: {e}")
            return None

    def get_historical(
        self,
        instrument_token: int,
        interval: str = "minute",
        days_back: int = 1,
    ):
        """
        Fetch historical OHLCV candles as a pandas DataFrame.

        Args:
            instrument_token: Kite instrument token (integer)
            interval:         "minute" | "5minute" | "15minute" | "day"
            days_back:        How many calendar days of data to fetch

        Returns:
            DataFrame with columns: datetime, open, high, low, close, volume
        """
        import pandas as pd

        try:
            from_dt = datetime.now(IST).replace(hour=9, minute=15, second=0) - timedelta(days=days_back - 1)
            to_dt   = datetime.now(IST)

            candles = self.kite.historical_data(
                instrument_token = instrument_token,
                from_date        = from_dt,
                to_date          = to_dt,
                interval         = interval,
                continuous       = False,
                oi               = False,
            )

            df = pd.DataFrame(candles)
            df["datetime"] = pd.to_datetime(df["date"]).dt.tz_convert(IST)
            df = df.set_index("datetime").drop(columns=["date"], errors="ignore")
            df = df[["open", "high", "low", "close", "volume"]]
            return df

        except Exception as e:
            logger.error(f"Historical data fetch error: {e}")
            return None

    def get_instruments(self, exchange: str = "NFO") -> list[dict]:
        """
        Fetch full instrument list for an exchange.
        Used to find option symbols and tokens.
        """
        try:
            return self.kite.instruments(exchange)
        except Exception as e:
            logger.error(f"Instruments fetch error: {e}")
            return []

    def get_quote(self, instruments: list[str]) -> dict:
        """Full quote (bid/ask, OI, volume, etc.) for instruments."""
        try:
            return self.kite.quote(instruments)
        except Exception as e:
            logger.error(f"Quote fetch error: {e}")
            return {}
