# utils/option_chain.py
# ─────────────────────────────────────────────────────────────────────────────
# Option Chain Analyzer — Dhan API edition
#
# Uses Dhan's option_chain() + expiry_list() to find the best option to buy.
# No instrument file download needed — all done via API.
# ─────────────────────────────────────────────────────────────────────────────

from datetime import datetime, date
from typing import Optional

from loguru import logger
from config.settings import INDICES, MIN_OI, MAX_SPREAD_PCT, IST


def get_nearest_weekly_expiry(dhan_client, symbol: str, is_index: bool = True) -> Optional[str]:
    """Return the nearest upcoming weekly expiry date string (YYYY-MM-DD).
    
    Args:
        dhan_client: Dhan API client instance
        symbol: Index (NIFTY, BANKNIFTY, FINNIFTY) or stock (TCS, INFY, etc.)
        is_index: If True, treats as index; if False, treats as stock
    """
    expiries = dhan_client.get_expiry_list(symbol, is_index=is_index)
    if not expiries:
        return None
    today = datetime.now(IST).date()
    upcoming = sorted(
        [e for e in expiries if date.fromisoformat(e) >= today]
    )
    return upcoming[0] if upcoming else None


def get_best_option(
    symbol:       str,
    spot_price:   float,
    option_type:  str,           # "CE" or "PE"
    max_premium:  float,
    dhan_client=None,
    is_index:     bool = True,   # If False, treat as stock option
    otm_offset:   int = 0,       # 0=ATM, 1=1 strike OTM, -1=1 strike ITM
    **kwargs,
) -> Optional[dict]:
    """
    Select the best option to buy using Dhan's option chain.
    
    Args:
        symbol: Index (NIFTY, BANKNIFTY, FINNIFTY) or stock (TCS, INFY, etc.)
        spot_price: Current spot price
        option_type: "CE" (call) or "PE" (put)
        max_premium: Maximum premium to pay
        dhan_client: Dhan API client instance
        is_index: If False, treat as stock option (different security ID lookup)
        otm_offset: Offset from ATM strike
        kwargs: Backward compatibility (kite alias for dhan_client)

    Returns:
        dict(symbol, strike, expiry, ltp, security_id) or None
    """
    # Backward-compatible alias used by strategy files.
    if dhan_client is None:
        dhan_client = kwargs.get("kite")
    if dhan_client is None:
        logger.error("Option chain lookup failed: missing dhan_client/kite instance")
        return None

    expiry = get_nearest_weekly_expiry(dhan_client, symbol, is_index=is_index)
    if not expiry:
        logger.warning(f"{symbol}: Could not fetch expiry list from Dhan")
        return None

    resp = dhan_client.get_option_chain(symbol, expiry, is_index=is_index)
    if not resp or resp.get("status") == "failure":
        logger.warning(f"{symbol}: Option chain fetch failed for expiry {expiry}")
        return None

    cfg  = INDICES[symbol]
    step = cfg["strike_step"]
    atm  = round(spot_price / step) * step

    # Determine base strike based on direction and otm_offset
    if option_type == "CE":
        base_strike = atm + otm_offset * step
    else:
        base_strike = atm - otm_offset * step

    chain_data = resp.get("data", {})

    # Try base strike then widen outward
    for adj in [0, 1, -1, 2, -2, 3, -3]:
        strike = int(base_strike + adj * step)
        strike_key = str(int(strike))

        row = chain_data.get(strike_key) or chain_data.get(str(float(strike)))
        if not row:
            continue

        side_key = "call_options" if option_type == "CE" else "put_options"
        side = row.get(side_key, {})
        if not side:
            continue

        mkt  = side.get("market_data", {})
        meta = side.get("option_data", {})

        ltp    = float(mkt.get("ltp", 0))
        oi     = int(mkt.get("oi", 0))
        bid    = float(mkt.get("bid_price", 0))
        ask    = float(mkt.get("ask_price", 0))
        sec_id = str(meta.get("security_id", ""))

        if ltp <= 0:
            continue
        if ltp > max_premium:
            logger.debug(f"{symbol} {option_type} {strike}: LTP ₹{ltp} > cap ₹{max_premium:.0f}")
            continue
        if oi < MIN_OI:
            logger.debug(f"{symbol} {option_type} {strike}: OI {oi} < {MIN_OI}")
            continue

        spread_pct = (ask - bid) / ltp if (ltp > 0 and ask > bid) else 0.0
        if spread_pct > MAX_SPREAD_PCT:
            logger.debug(f"{symbol} {option_type} {strike}: spread {spread_pct:.2%} too wide")
            continue

        # Build a readable trading symbol (e.g. NIFTY24OCT22000CE or TCS24OCT2650CE)
        exp_dt = date.fromisoformat(expiry)
        symbol_name = symbol.replace(" ", "")  # Remove spaces for symbol (HDFC BANK → HDFCBANK)
        trading_symbol = (
            f"{symbol_name}"
            f"{str(exp_dt.year)[2:]}"
            f"{exp_dt.strftime('%b').upper()}"
            f"{strike}"
            f"{option_type}"
        )

        logger.info(
            f"✔ {trading_symbol} | LTP=₹{ltp} OI={oi:,} "
            f"Spread={spread_pct:.2%} Expiry={expiry}"
        )
        return {
            "symbol":      trading_symbol,
            "strike":      strike,
            "expiry":      expiry,
            "ltp":         ltp,
            "security_id": sec_id,
        }

    logger.warning(
        f"No valid {symbol} {option_type} near {base_strike} "
        f"(spot={spot_price:.0f} cap=₹{max_premium:.0f})"
    )
    return None
