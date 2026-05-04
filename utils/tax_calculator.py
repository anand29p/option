# utils/tax_calculator.py
# ─────────────────────────────────────────────────────────────────────────────
# Calculates all Indian regulatory charges for option buying trades.
# Called on every trade entry AND exit to get net P&L.
#
# Charges included (FY 2024-25):
#   - STT (Securities Transaction Tax)
#   - NSE Exchange Transaction Charges
#   - SEBI Turnover Fee
#   - Stamp Duty
#   - Zerodha Brokerage (flat ₹20 per order)
#   - GST (18% on brokerage + exchange charges)
# ─────────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass, field
from config.settings import TAX
from loguru import logger


@dataclass
class TradeCharges:
    """Complete breakdown of charges for one trade leg (buy or sell)."""
    premium:           float = 0.0
    quantity:          int   = 0   # total units (lots × lot_size)
    turnover:          float = 0.0

    stt:               float = 0.0
    nse_txn_charge:    float = 0.0
    sebi_fee:          float = 0.0
    stamp_duty:        float = 0.0
    brokerage:         float = 0.0
    gst:               float = 0.0

    total_charges:     float = 0.0


@dataclass
class TradePnL:
    """Net P&L for a round-trip option buy trade."""
    entry_price:       float = 0.0
    exit_price:        float = 0.0
    quantity:          int   = 0

    gross_pnl:         float = 0.0
    entry_charges:     TradeCharges = field(default_factory=TradeCharges)
    exit_charges:      TradeCharges = field(default_factory=TradeCharges)
    total_charges:     float = 0.0
    net_pnl:           float = 0.0
    net_pnl_pct:       float = 0.0   # % of capital deployed

    charge_breakdown:  dict  = field(default_factory=dict)


def _compute_leg_charges(premium: float, quantity: int, is_buy: bool) -> TradeCharges:
    """
    Compute all charges for a single leg (entry or exit).

    Args:
        premium:   LTP of the option at execution (₹ per unit)
        quantity:  Total units (lots × lot_size)
        is_buy:    True for entry (buy), False for exit (sell)

    Returns:
        TradeCharges with all fields populated
    """
    c = TradeCharges()
    c.premium  = premium
    c.quantity = quantity
    c.turnover = premium * quantity

    # STT: only on buy side for option buyers (0.1% of premium paid)
    # On sell side, STT for option buyers is 0 (it's on the writer)
    c.stt = (c.turnover * TAX["stt_buy_pct"]) if is_buy else 0.0

    # NSE Exchange Transaction Charge: 0.053% of turnover (both sides)
    c.nse_txn_charge = c.turnover * TAX["nse_txn_charge_pct"]

    # SEBI Turnover Fee: ₹10 per crore
    c.sebi_fee = (c.turnover / 1_00_00_000) * TAX["sebi_fee_per_crore"]

    # Stamp Duty: 0.003% on buy side only
    c.stamp_duty = (c.turnover * TAX["stamp_duty_pct"]) if is_buy else 0.0

    # Zerodha flat brokerage per order
    c.brokerage = TAX["brokerage_per_order"]

    # GST: 18% on (brokerage + nse transaction charge)
    c.gst = (c.brokerage + c.nse_txn_charge) * TAX["gst_pct"]

    c.total_charges = (
        c.stt + c.nse_txn_charge + c.sebi_fee +
        c.stamp_duty + c.brokerage + c.gst
    )

    return c


def calculate_net_pnl(
    entry_price: float,
    exit_price:  float,
    quantity:    int,
) -> TradePnL:
    """
    Calculate net P&L for a complete round-trip option buy trade.

    Args:
        entry_price: Premium paid at entry (₹ per unit)
        exit_price:  Premium received at exit (₹ per unit)
        quantity:    Total units traded (lots × lot_size)

    Returns:
        TradePnL with gross P&L, all charges, and net P&L
    """
    result = TradePnL()
    result.entry_price = entry_price
    result.exit_price  = exit_price
    result.quantity    = quantity

    result.gross_pnl = (exit_price - entry_price) * quantity

    result.entry_charges = _compute_leg_charges(entry_price, quantity, is_buy=True)
    result.exit_charges  = _compute_leg_charges(exit_price,  quantity, is_buy=False)

    result.total_charges = (
        result.entry_charges.total_charges +
        result.exit_charges.total_charges
    )

    result.net_pnl = result.gross_pnl - result.total_charges

    capital_deployed = entry_price * quantity
    result.net_pnl_pct = (
        (result.net_pnl / capital_deployed * 100)
        if capital_deployed > 0 else 0.0
    )

    result.charge_breakdown = {
        "stt":            round(result.entry_charges.stt, 2),
        "nse_txn":        round(result.entry_charges.nse_txn_charge + result.exit_charges.nse_txn_charge, 2),
        "sebi_fee":       round(result.entry_charges.sebi_fee + result.exit_charges.sebi_fee, 4),
        "stamp_duty":     round(result.entry_charges.stamp_duty, 2),
        "brokerage":      round(result.entry_charges.brokerage + result.exit_charges.brokerage, 2),
        "gst":            round(result.entry_charges.gst + result.exit_charges.gst, 2),
        "total_charges":  round(result.total_charges, 2),
        "gross_pnl":      round(result.gross_pnl, 2),
        "net_pnl":        round(result.net_pnl, 2),
        "net_pnl_pct":    round(result.net_pnl_pct, 2),
    }

    logger.debug(
        f"P&L | Entry={entry_price} Exit={exit_price} Qty={quantity} | "
        f"Gross=₹{result.gross_pnl:.2f} Charges=₹{result.total_charges:.2f} "
        f"Net=₹{result.net_pnl:.2f} ({result.net_pnl_pct:.2f}%)"
    )

    return result


def daily_tax_summary(trades: list[dict]) -> dict:
    """
    Aggregate all charges and P&L for a list of closed trades for the day.

    Args:
        trades: List of dicts each with keys:
                entry_price, exit_price, quantity

    Returns:
        Dict with totals for each charge type and net P&L
    """
    totals = {
        "trades":         len(trades),
        "gross_pnl":      0.0,
        "stt":            0.0,
        "nse_txn":        0.0,
        "sebi_fee":       0.0,
        "stamp_duty":     0.0,
        "brokerage":      0.0,
        "gst":            0.0,
        "total_charges":  0.0,
        "net_pnl":        0.0,
        "winners":        0,
        "losers":         0,
    }

    for t in trades:
        pnl = calculate_net_pnl(t["entry_price"], t["exit_price"], t["quantity"])
        bd  = pnl.charge_breakdown
        totals["gross_pnl"]     += bd["gross_pnl"]
        totals["stt"]           += bd["stt"]
        totals["nse_txn"]       += bd["nse_txn"]
        totals["sebi_fee"]      += bd["sebi_fee"]
        totals["stamp_duty"]    += bd["stamp_duty"]
        totals["brokerage"]     += bd["brokerage"]
        totals["gst"]           += bd["gst"]
        totals["total_charges"] += bd["total_charges"]
        totals["net_pnl"]       += bd["net_pnl"]
        if bd["net_pnl"] >= 0:
            totals["winners"] += 1
        else:
            totals["losers"] += 1

    totals["win_rate"] = (
        round(totals["winners"] / totals["trades"] * 100, 1)
        if totals["trades"] > 0 else 0.0
    )
    return {k: round(v, 2) if isinstance(v, float) else v for k, v in totals.items()}
