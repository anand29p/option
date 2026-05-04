# utils/option_chain.py
# ─────────────────────────────────────────────────────────────────────────────
# Option Chain Analyzer
# Finds the best option to buy for a given signal:
#   - Nearest weekly expiry
#   - ATM or slight OTM strike
#   - Filters by OI, bid-ask spread
#   - Returns symbol, strike, expiry, LTP
# ─────────────────────────────────────────────────────────────────────────────

import pandas as pd
from datetime import datetime, date
from typing import Optional
from loguru import logger

from config.settings import (
    INDICES, MIN_OI, MAX_SPREAD_PCT, IST, EXPIRY_TYPE
)


# Cache instruments list to avoid repeated API calls (refresh once per day)
_instruments_cache: dict = {}
_cache_date: Optional[date] = None


def _get_instruments(kite, exchange: str = "NFO") -> pd.DataFrame:
    global _instruments_cache, _cache_date
    today = datetime.now(IST).date()

    if _cache_date != today or exchange not in _instruments_cache:
        raw = kite.get_instruments(exchange)
        _instruments_cache[exchange] = pd.DataFrame(raw)
        _cache_date = today
        logger.debug(f"Instruments cache refreshed for {exchange} ({len(raw)} instruments)")

    return _instruments_cache[exchange]


def get_nearest_weekly_expiry(kite, index: str) -> Optional[date]:
    """
    Find the nearest upcoming weekly expiry for an index.

    Returns:
        date object of nearest weekly expiry, or None
    """
    df    = _get_instruments(kite)
    today = datetime.now(IST).date()

    # Filter by index name and option type
    mask = (
        df["name"].str.upper() == index.upper().replace("NIFTY", "NIFTY").replace("BANKNIFTY", "BANKNIFTY") &
        df["instrument_type"].isin(["CE", "PE"]) &
        df["segment"] == "NFO-OPT"
    )
    sub = df[mask].copy()

    if sub.empty:
        return None

    sub["expiry"] = pd.to_datetime(sub["expiry"]).dt.date
    future_expiries = sorted(e for e in sub["expiry"].unique() if e >= today)

    return future_expiries[0] if future_expiries else None


def get_best_option(
    kite,
    index:       str,
    spot_price:  float,
    option_type: str,   # "CE" | "PE"
    max_premium: float, # max premium per unit
    otm_offset:  int = 0,  # 0=ATM, 1=1 strike OTM, etc.
) -> Optional[dict]:
    """
    Select the best option contract to buy.

    Selection criteria:
    1. Nearest weekly expiry
    2. ATM strike (or OTM by otm_offset strikes)
    3. LTP ≤ max_premium
    4. OI ≥ MIN_OI
    5. Bid-ask spread ≤ MAX_SPREAD_PCT of LTP

    Returns:
        dict with keys: symbol, strike, expiry, ltp, token
        or None if no suitable option found
    """
    idx_cfg     = INDICES[index]
    strike_step = idx_cfg["strike_step"]

    # Round spot to nearest strike
    atm_strike = round(spot_price / strike_step) * strike_step

    # Apply OTM offset
    if option_type == "CE":
        target_strike = atm_strike + otm_offset * strike_step
    else:
        target_strike = atm_strike - otm_offset * strike_step

    # Get instruments
    df = _get_instruments(kite)

    # Normalize index name for instrument lookup
    name_map = {
        "NIFTY":     "NIFTY",
        "BANKNIFTY": "BANKNIFTY",
        "FINNIFTY":  "FINNIFTY",
    }
    instrument_name = name_map.get(index, index)

    today = datetime.now(IST).date()
    df["expiry_date"] = pd.to_datetime(df["expiry"]).dt.date

    # Filter
    candidates = df[
        (df["name"].str.upper() == instrument_name) &
        (df["instrument_type"] == option_type) &
        (df["expiry_date"] >= today) &
        (df["strike"] == target_strike)
    ].copy()

    # Prefer nearest expiry
    if candidates.empty:
        logger.warning(f"No options found for {index} {option_type} strike {target_strike}")
        return None

    candidates = candidates.sort_values("expiry_date")
    best = candidates.iloc[0]

    symbol = best["tradingsymbol"]
    token  = best["instrument_token"]

    # Fetch live quote for LTP, OI, bid-ask
    try:
        quote = kite.get_quote([f"NFO:{symbol}"])
        q     = quote.get(f"NFO:{symbol}", {})

        ltp    = q.get("last_price", 0)
        oi     = q.get("oi", 0)
        depth  = q.get("depth", {})
        best_bid = depth.get("buy",  [{}])[0].get("price", 0)
        best_ask = depth.get("sell", [{}])[0].get("price", 0)

    except Exception as e:
        logger.error(f"Quote fetch failed for {symbol}: {e}")
        return None

    # Validate
    if ltp <= 0:
        logger.debug(f"{symbol}: LTP=0, skipping")
        return None

    if ltp > max_premium:
        logger.debug(f"{symbol}: LTP={ltp} > max_premium={max_premium}, skipping")
        return None

    if oi < MIN_OI:
        logger.debug(f"{symbol}: OI={oi} < MIN_OI={MIN_OI}, skipping")
        return None

    spread_pct = (best_ask - best_bid) / ltp if ltp > 0 else 999
    if spread_pct > MAX_SPREAD_PCT:
        logger.debug(f"{symbol}: Spread={spread_pct:.3f} > MAX={MAX_SPREAD_PCT}, skipping")
        return None

    logger.info(
        f"✔ Option selected: {symbol} | LTP={ltp} | OI={oi:,} | "
        f"Spread={spread_pct:.2%} | Expiry={best['expiry_date']}"
    )

    return {
        "symbol":  symbol,
        "strike":  int(target_strike),
        "expiry":  str(best["expiry_date"]),
        "ltp":     ltp,
        "token":   token,
    }
