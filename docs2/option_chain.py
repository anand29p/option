# utils/option_chain.py
# ─────────────────────────────────────────────────────────────────────────────
# Option Chain Analyzer
# Finds the best option to buy for a given signal:
#   - Nearest weekly expiry
#   - ATM or slight OTM/ITM strike
#   - Filters by OI, bid-ask spread, premium cap
#   - Falls back to adjacent strikes automatically
# ─────────────────────────────────────────────────────────────────────────────

import pandas as pd
from datetime import datetime, date
from typing import Optional
from loguru import logger

from config.settings import INDICES, MIN_OI, MAX_SPREAD_PCT, IST

# ── Instrument Cache (refresh once per day) ───────────────────────────────────
_instruments_cache: dict[str, pd.DataFrame] = {}
_cache_date: Optional[date] = None


def _get_instruments(kite, exchange: str = "NFO") -> pd.DataFrame:
    global _instruments_cache, _cache_date
    today = datetime.now(IST).date()

    if _cache_date != today or exchange not in _instruments_cache:
        raw = kite.get_instruments(exchange)
        df  = pd.DataFrame(raw)
        df["name"]            = df["name"].str.upper().str.strip()
        df["instrument_type"] = df["instrument_type"].str.upper().str.strip()
        df["expiry_date"]     = pd.to_datetime(df["expiry"]).dt.date
        _instruments_cache[exchange] = df
        _cache_date = today
        logger.debug(f"Instruments cache refreshed: {exchange} ({len(df)} rows)")

    return _instruments_cache[exchange]


def get_nearest_weekly_expiry(kite, index: str) -> Optional[date]:
    """Return the nearest upcoming weekly expiry date for an index."""
    df    = _get_instruments(kite)
    today = datetime.now(IST).date()
    iname = index.upper().replace("FINNIFTY", "FINNIFTY")

    sub = df[
        (df["name"] == iname) &
        (df["instrument_type"].isin(["CE", "PE"])) &
        (df["expiry_date"] >= today)
    ]
    if sub.empty:
        return None
    return sorted(sub["expiry_date"].unique())[0]


def get_best_option(
    kite,
    index:       str,
    spot_price:  float,
    option_type: str,
    max_premium: float,
    otm_offset:  int = 0,
) -> Optional[dict]:
    """
    Select the best option to buy.

    Args:
        kite:         KiteClient instance
        index:        NIFTY | BANKNIFTY | FINNIFTY
        spot_price:   Current index level
        option_type:  CE | PE
        max_premium:  Max allowed LTP per unit (₹)
        otm_offset:   0=ATM, 1=1 strike OTM, -1=1 strike ITM

    Returns:
        dict(symbol, strike, expiry, ltp, token) or None
    """
    cfg         = INDICES[index]
    step        = cfg["strike_step"]
    today       = datetime.now(IST).date()
    atm         = round(spot_price / step) * step
    iname       = index.upper()

    if option_type == "CE":
        base_strike = atm + otm_offset * step
    else:
        base_strike = atm - otm_offset * step

    df = _get_instruments(kite)

    # Try base strike then widen outward until we find a valid option
    for adj in [0, 1, -1, 2, -2, 3, -3]:
        strike = int(base_strike + adj * step)

        rows = df[
            (df["name"] == iname) &
            (df["instrument_type"] == option_type.upper()) &
            (df["expiry_date"] >= today) &
            (df["strike"] == strike)
        ].sort_values("expiry_date")

        if rows.empty:
            continue

        row    = rows.iloc[0]
        symbol = row["tradingsymbol"]
        token  = int(row["instrument_token"])

        try:
            quote = kite.get_quote([f"NFO:{symbol}"])
            q     = quote.get(f"NFO:{symbol}", {})
        except Exception as e:
            logger.error(f"Quote error for {symbol}: {e}")
            continue

        ltp = q.get("last_price", 0.0)
        oi  = q.get("oi", 0)
        depth = q.get("depth", {})
        bid   = (depth.get("buy",  [{}]) or [{}])[0].get("price", 0)
        ask   = (depth.get("sell", [{}]) or [{}])[0].get("price", 0)

        if ltp <= 0:
            continue
        if ltp > max_premium:
            logger.debug(f"{symbol} LTP ₹{ltp} > cap ₹{max_premium:.0f}")
            continue
        if oi < MIN_OI:
            logger.debug(f"{symbol} OI {oi} < {MIN_OI}")
            continue
        spread_pct = (ask - bid) / ltp if (ltp > 0 and ask > bid) else 0.0
        if spread_pct > MAX_SPREAD_PCT:
            logger.debug(f"{symbol} spread {spread_pct:.2%} too wide")
            continue

        logger.info(
            f"✔ {symbol} | LTP=₹{ltp} OI={oi:,} "
            f"Spread={spread_pct:.2%} Expiry={row['expiry_date']}"
        )
        return {
            "symbol": symbol,
            "strike": strike,
            "expiry": str(row["expiry_date"]),
            "ltp":    ltp,
            "token":  token,
        }

    logger.warning(
        f"No valid {index} {option_type} near {base_strike} "
        f"(spot={spot_price:.0f} cap=₹{max_premium:.0f})"
    )
    return None
