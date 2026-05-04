# utils/global_context.py
# ─────────────────────────────────────────────────────────────────────────────
# Global Market Context
#
# Fetches GIFT Nifty + key international indices via yfinance (free, no API key).
# Used by StrategySelector to bias trading decisions before/during market hours.
#
# Indices tracked:
#   GIFT Nifty Futures (SGX Nifty proxy): ^NSEI or NIFTY_FUT
#   Dow Jones:    ^DJI     Nasdaq:    ^IXIC
#   S&P 500:      ^GSPC    Nikkei:    ^N225
#   Hang Seng:    ^HSI     DAX:       ^GDAXI
#   FTSE 100:     ^FTSE    Crude Oil: CL=F
#   USD/INR:      INR=X
# ─────────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from typing import Optional
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd
import yfinance as yf
from loguru import logger

from config.settings import IST

# ── Tracked symbols ───────────────────────────────────────────────────────────
GLOBAL_SYMBOLS = {
    # Indian
    "GIFT_NIFTY":  "^NSEI",      # Nearest proxy; actual GIFT futures not on yfinance
    # US
    "DOW":         "^DJI",
    "SP500":       "^GSPC",
    "NASDAQ":      "^IXIC",
    # Asia
    "NIKKEI":      "^N225",
    "HANG_SENG":   "^HSI",
    # Europe
    "DAX":         "^GDAXI",
    "FTSE":        "^FTSE",
    # Commodities / FX
    "CRUDE_OIL":   "CL=F",
    "USD_INR":     "INR=X",
}


@dataclass
class GlobalContext:
    """Snapshot of global market conditions at a point in time."""
    timestamp:       datetime = field(default_factory=lambda: datetime.now(IST))
    prices:          dict     = field(default_factory=dict)   # {name: current_price}
    pct_changes:     dict     = field(default_factory=dict)   # {name: % change today}
    us_bias:         str      = "NEUTRAL"   # BULLISH | BEARISH | NEUTRAL
    asia_bias:       str      = "NEUTRAL"
    overall_bias:    str      = "NEUTRAL"
    gift_nifty_chg:  Optional[float] = None   # % change in GIFT Nifty (pre-market indicator)
    crude_chg:       Optional[float] = None   # % change in crude oil
    provider:        str      = "NONE"       # TWELVE_DATA | ALPHA_VANTAGE | YFINANCE | NONE

    def to_dict(self) -> dict:
        return {
            "timestamp":    self.timestamp.strftime("%H:%M:%S IST"),
            "prices":       {k: round(v, 2) for k, v in self.prices.items()},
            "pct_changes":  {k: round(v, 3) for k, v in self.pct_changes.items()},
            "us_bias":      self.us_bias,
            "asia_bias":    self.asia_bias,
            "overall_bias": self.overall_bias,
            "gift_nifty_chg": self.gift_nifty_chg,
            "crude_chg":    self.crude_chg,
            "provider":     self.provider,
        }


class GlobalContextFetcher:
    """
    Fetches global market data and computes a sentiment bias.
    Call fetch() once per strategy cycle (caches result for 5 min).
    """

    def __init__(self, cache_seconds: int = 300):
        self._cache_seconds = cache_seconds
        self._cached:   Optional[GlobalContext] = None
        self._cached_at: Optional[datetime]     = None

    def fetch(self, force: bool = False) -> GlobalContext:
        """
        Return GlobalContext. Uses cache unless stale or force=True.
        Never raises — returns last good cache or empty context on failure.
        """
        now = datetime.now(IST)
        if (not force
                and self._cached is not None
                and self._cached_at is not None
                and (now - self._cached_at).total_seconds() < self._cache_seconds):
            return self._cached

        try:
            ctx = self._fetch_fresh()
            self._cached    = ctx
            self._cached_at = now
            logger.debug(
                f"🌍 Global bias: US={ctx.us_bias} Asia={ctx.asia_bias} "
                f"Overall={ctx.overall_bias} | GIFT={ctx.gift_nifty_chg:+.2f}% "
                f"Crude={ctx.crude_chg:+.2f}%"
                if ctx.gift_nifty_chg is not None and ctx.crude_chg is not None
                else f"🌍 Global bias: {ctx.overall_bias}"
            )
            logger.debug(f"🌐 Global data provider: {ctx.provider}")
            return ctx
        except Exception as e:
            logger.warning(f"GlobalContext fetch failed: {e}")
            return self._cached or GlobalContext()

    def _fetch_fresh(self) -> GlobalContext:
        # Prefer Twelve Data, then Alpha Vantage, then yfinance fallback.
        twelve_ctx = self._fetch_twelve_data()
        if twelve_ctx is not None and twelve_ctx.prices:
            return twelve_ctx

        alpha_ctx = self._fetch_alpha_vantage()
        if alpha_ctx is not None and alpha_ctx.prices:
            return alpha_ctx

        return self._fetch_yfinance()

    def _fetch_twelve_data(self) -> Optional[GlobalContext]:
        api_key = _get_twelve_data_api_key()
        if not api_key:
            return None

        # Liquid ETF proxies improve cross-provider symbol reliability.
        td_symbols = {
            "GIFT_NIFTY": "INDY",
            "DOW": "DIA",
            "SP500": "SPY",
            "NASDAQ": "QQQ",
            "NIKKEI": "EWJ",
            "HANG_SENG": "EWH",
            "DAX": "EWG",
            "FTSE": "EWU",
            "CRUDE_OIL": "USO",
            "USD_INR": "USD/INR",
        }

        prices = {}
        pct_chgs = {}

        for name, sym in td_symbols.items():
            payload = _td_get_json(
                {
                    "symbol": sym,
                    "apikey": api_key,
                }
            )
            if payload is None:
                continue

            try:
                curr = float(payload.get("close", "") or 0)
                if curr <= 0:
                    continue
                prices[name] = curr

                chg = payload.get("percent_change")
                if chg is not None and chg != "":
                    pct_chgs[name] = float(chg)
            except Exception:
                continue

        if not prices:
            return None

        us_indices = ["DOW", "SP500", "NASDAQ"]
        asia_indices = ["NIKKEI", "HANG_SENG"]

        us_chg = _avg_chg(pct_chgs, us_indices)
        asia_chg = _avg_chg(pct_chgs, asia_indices)
        all_chg = _avg_chg(pct_chgs, us_indices + asia_indices)

        return GlobalContext(
            prices=prices,
            pct_changes=pct_chgs,
            us_bias=_bias(us_chg),
            asia_bias=_bias(asia_chg),
            overall_bias=_bias(all_chg),
            gift_nifty_chg=pct_chgs.get("GIFT_NIFTY"),
            crude_chg=pct_chgs.get("CRUDE_OIL"),
            provider="TWELVE_DATA",
        )

    def _fetch_alpha_vantage(self) -> Optional[GlobalContext]:
        api_key = os.getenv("ALPHA_VANTAGE_KEY", "").strip()
        if not api_key:
            return None

        # Alpha Vantage index coverage is limited; ETFs are stable liquid proxies.
        av_symbols = {
            "GIFT_NIFTY": "INDY",   # iShares India 50 ETF proxy
            "DOW": "DIA",
            "SP500": "SPY",
            "NASDAQ": "QQQ",
            "NIKKEI": "EWJ",
            "HANG_SENG": "EWH",
            "DAX": "EWG",
            "FTSE": "EWU",
            "CRUDE_OIL": "USO",
        }

        prices = {}
        pct_chgs = {}

        for name, sym in av_symbols.items():
            payload = _av_get_json(
                {
                    "function": "GLOBAL_QUOTE",
                    "symbol": sym,
                    "apikey": api_key,
                }
            )

            if payload is None:
                continue

            quote = payload.get("Global Quote", {})
            try:
                curr = float(quote.get("05. price", "") or 0)
                prev = float(quote.get("08. previous close", "") or 0)
                if curr <= 0:
                    continue
                pct = ((curr - prev) / prev) * 100 if prev else None
                prices[name] = curr
                if pct is not None:
                    pct_chgs[name] = pct
            except Exception:
                continue

        # USD/INR from FX endpoint
        fx_payload = _av_get_json(
            {
                "function": "CURRENCY_EXCHANGE_RATE",
                "from_currency": "USD",
                "to_currency": "INR",
                "apikey": api_key,
            }
        )
        if fx_payload is not None:
            fx_data = fx_payload.get("Realtime Currency Exchange Rate", {})
            try:
                prices["USD_INR"] = float(fx_data.get("5. Exchange Rate", "") or 0)
            except Exception:
                pass

        if not prices:
            return None

        us_indices = ["DOW", "SP500", "NASDAQ"]
        asia_indices = ["NIKKEI", "HANG_SENG"]

        us_chg = _avg_chg(pct_chgs, us_indices)
        asia_chg = _avg_chg(pct_chgs, asia_indices)
        all_chg = _avg_chg(pct_chgs, us_indices + asia_indices)

        return GlobalContext(
            prices=prices,
            pct_changes=pct_chgs,
            us_bias=_bias(us_chg),
            asia_bias=_bias(asia_chg),
            overall_bias=_bias(all_chg),
            gift_nifty_chg=pct_chgs.get("GIFT_NIFTY"),
            crude_chg=pct_chgs.get("CRUDE_OIL"),
            provider="ALPHA_VANTAGE",
        )

    def _fetch_yfinance(self) -> GlobalContext:
        tickers = yf.download(
            tickers=list(GLOBAL_SYMBOLS.values()),
            period="2d",
            interval="1d",
            progress=False,
            auto_adjust=True,
            timeout=5,
        )

        prices     = {}
        pct_chgs   = {}

        for name, sym in GLOBAL_SYMBOLS.items():
            try:
                series = _extract_close_series(tickers, sym)
                if len(series) < 2:
                    continue
                prev  = float(series.iloc[-2])
                curr  = float(series.iloc[-1])
                pct   = ((curr - prev) / prev) * 100 if prev else 0.0
                prices[name]   = curr
                pct_chgs[name] = pct
            except Exception:
                continue

        # Compute directional biases
        us_indices   = ["DOW", "SP500", "NASDAQ"]
        asia_indices = ["NIKKEI", "HANG_SENG"]

        us_chg   = _avg_chg(pct_chgs, us_indices)
        asia_chg = _avg_chg(pct_chgs, asia_indices)
        all_chg  = _avg_chg(pct_chgs, us_indices + asia_indices)

        us_bias   = _bias(us_chg)
        asia_bias = _bias(asia_chg)
        overall   = _bias(all_chg)

        return GlobalContext(
            prices=prices,
            pct_changes=pct_chgs,
            us_bias=us_bias,
            asia_bias=asia_bias,
            overall_bias=overall,
            gift_nifty_chg=pct_chgs.get("GIFT_NIFTY"),
            crude_chg=pct_chgs.get("CRUDE_OIL"),
            provider="YFINANCE",
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _avg_chg(changes: dict, keys: list) -> float:
    vals = [changes[k] for k in keys if k in changes]
    return sum(vals) / len(vals) if vals else 0.0


def _bias(avg_chg: float, threshold: float = 0.3) -> str:
    if avg_chg > threshold:
        return "BULLISH"
    elif avg_chg < -threshold:
        return "BEARISH"
    return "NEUTRAL"


def _extract_close_series(tickers_df: pd.DataFrame, symbol: str) -> pd.Series:
    """Return a close-price series for a symbol from yfinance download output."""
    if tickers_df.empty:
        return pd.Series(dtype="float64")

    columns = tickers_df.columns

    if isinstance(columns, pd.MultiIndex):
        # yfinance can return (Price, Ticker) or (Ticker, Price).
        if ("Close", symbol) in columns:
            series = tickers_df[("Close", symbol)]
        elif (symbol, "Close") in columns:
            series = tickers_df[(symbol, "Close")]
        else:
            return pd.Series(dtype="float64")
    else:
        if "Close" not in columns:
            return pd.Series(dtype="float64")
        series = tickers_df["Close"]

    return series.dropna()


def _av_get_json(params: dict) -> Optional[dict]:
    """Call Alpha Vantage and return parsed JSON, handling rate-limit payloads."""
    url = "https://www.alphavantage.co/query?" + urlencode(params)
    try:
        with urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.debug(f"Alpha Vantage request failed: {e}")
        return None

    if not isinstance(data, dict):
        return None

    if "Note" in data:
        logger.warning(f"Alpha Vantage rate limit: {data.get('Note')}")
        return None

    if "Error Message" in data:
        logger.debug(f"Alpha Vantage error: {data.get('Error Message')}")
        return None

    return data


def _get_twelve_data_api_key() -> str:
    """Return Twelve Data API key from common environment variable names."""
    return (
        os.getenv("TWELVE_DATA_API_KEY", "").strip()
        or os.getenv("TWELVEDATA_API_KEY", "").strip()
        or os.getenv("TWELVE_API_KEY", "").strip()
    )


def _td_get_json(params: dict) -> Optional[dict]:
    """Call Twelve Data quote endpoint and return parsed JSON payload."""
    url = "https://api.twelvedata.com/quote?" + urlencode(params)
    try:
        with urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.debug(f"Twelve Data request failed: {e}")
        return None

    if not isinstance(data, dict):
        return None

    if "code" in data and str(data.get("code", "")).startswith("4"):
        logger.debug(f"Twelve Data error: {data.get('message', data.get('code'))}")
        return None

    if data.get("status") == "error":
        logger.debug(f"Twelve Data status error: {data.get('message', 'unknown error')}")
        return None

    return data


# Module-level singleton
_fetcher = GlobalContextFetcher(cache_seconds=300)


def get_global_context(force: bool = False) -> GlobalContext:
    """Convenience function — use this in strategies."""
    return _fetcher.fetch(force=force)
