import pytest
from utils.tax_calculator import _compute_leg_charges, calculate_net_pnl


def test_compute_leg_charges_buy():
    # Example: Buy NIFTY 1 lot (25 qty) at ₹100
    premium = 100.0
    qty = 25
    charges = _compute_leg_charges(premium, qty, is_buy=True)

    assert charges.turnover == 2500.0
    assert charges.stt == 2500.0 * 0.001          # 2.5
    assert charges.nse_txn_charge == 2500.0 * 0.00053  # 1.325
    assert charges.stamp_duty == 2500.0 * 0.00003     # 0.075
    assert charges.brokerage == 20.0
    assert charges.gst == (20.0 + 1.325) * 0.18        # ~3.8385

    assert charges.total_charges > 27.0


def test_compute_leg_charges_sell():
    # Example: Sell NIFTY 1 lot (25 qty) at ₹150
    premium = 150.0
    qty = 25
    charges = _compute_leg_charges(premium, qty, is_buy=False)

    assert charges.turnover == 3750.0
    assert charges.stt == 0.0                      # No STT for option seller in this context (buyer pays)
    assert charges.nse_txn_charge == 3750.0 * 0.00053  # 1.9875
    assert charges.stamp_duty == 0.0               # Stamp duty only on buy
    assert charges.brokerage == 20.0
    assert charges.gst == (20.0 + 1.9875) * 0.18       # ~3.9577


def test_calculate_net_pnl():
    # Profitable trade: Buy at 100, Sell at 120 (Qty 25)
    # Capital Deployed = 2500
    # Gross PnL = 500
    pnl = calculate_net_pnl(100.0, 120.0, 25)

    assert pnl.gross_pnl == 500.0
    assert pnl.entry_charges.total_charges > 27.0
    assert pnl.exit_charges.total_charges > 25.0
    assert pnl.total_charges > 52.0

    assert pnl.net_pnl == pnl.gross_pnl - pnl.total_charges
    assert pnl.net_pnl_pct == (pnl.net_pnl / 2500.0) * 100.0

    # Ensure breakdown is populated
    assert "gross_pnl" in pnl.charge_breakdown
    assert "net_pnl" in pnl.charge_breakdown
    assert "stt" in pnl.charge_breakdown


def test_calculate_net_pnl_loss():
    # Losing trade: Buy at 100, Sell at 70 (Qty 25)
    pnl = calculate_net_pnl(100.0, 70.0, 25)

    assert pnl.gross_pnl == -750.0
    assert pnl.net_pnl < -750.0  # Loss increases because of charges
    assert pnl.net_pnl_pct < -30.0 # More than 30% loss
