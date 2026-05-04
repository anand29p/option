# tests/test_tax_calculator.py
# ─────────────────────────────────────────────────────────────────────────────
# Unit tests for Indian tax charge calculations.
# Run with: pytest tests/ -v
# ─────────────────────────────────────────────────────────────────────────────

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from utils.tax_calculator import calculate_net_pnl, daily_tax_summary, _compute_leg_charges


class TestLegCharges:
    """Test individual leg charge calculations."""

    def test_stt_only_on_buy(self):
        """STT should apply on buy side only for option buyers."""
        buy_charges  = _compute_leg_charges(premium=100.0, quantity=25, is_buy=True)
        sell_charges = _compute_leg_charges(premium=150.0, quantity=25, is_buy=False)

        assert buy_charges.stt > 0,   "STT must be > 0 on buy"
        assert sell_charges.stt == 0, "STT must be 0 on sell (option buyer)"

    def test_stt_rate(self):
        """STT = 0.1% of premium paid."""
        c = _compute_leg_charges(premium=200.0, quantity=50, is_buy=True)
        expected_stt = 200.0 * 50 * 0.001
        assert abs(c.stt - expected_stt) < 0.01

    def test_stamp_duty_only_on_buy(self):
        buy  = _compute_leg_charges(premium=100.0, quantity=25, is_buy=True)
        sell = _compute_leg_charges(premium=100.0, quantity=25, is_buy=False)
        assert buy.stamp_duty > 0
        assert sell.stamp_duty == 0

    def test_brokerage_flat(self):
        """Zerodha charges ₹20 flat per order regardless of size."""
        c1 = _compute_leg_charges(premium=50.0,   quantity=25, is_buy=True)
        c2 = _compute_leg_charges(premium=5000.0, quantity=50, is_buy=True)
        assert c1.brokerage == 20.0
        assert c2.brokerage == 20.0

    def test_gst_on_brokerage_and_txn(self):
        """GST = 18% of (brokerage + NSE transaction charge)."""
        c = _compute_leg_charges(premium=100.0, quantity=25, is_buy=True)
        expected_gst = (c.brokerage + c.nse_txn_charge) * 0.18
        assert abs(c.gst - expected_gst) < 0.001

    def test_total_charges_sum(self):
        """total_charges must equal sum of all components."""
        c = _compute_leg_charges(premium=150.0, quantity=75, is_buy=True)
        expected = c.stt + c.nse_txn_charge + c.sebi_fee + c.stamp_duty + c.brokerage + c.gst
        assert abs(c.total_charges - expected) < 0.001


class TestNetPnL:
    """Test round-trip P&L calculations."""

    def test_profitable_trade(self):
        """Net P&L should be positive after charges on a profitable trade."""
        pnl = calculate_net_pnl(entry_price=100.0, exit_price=140.0, quantity=25)
        assert pnl.gross_pnl == pytest.approx(1000.0)   # (140-100) × 25
        assert pnl.net_pnl < pnl.gross_pnl               # charges reduce P&L
        assert pnl.net_pnl > 0                            # still profitable

    def test_loss_trade(self):
        """Net P&L should be negative (larger loss) after charges on a losing trade."""
        pnl = calculate_net_pnl(entry_price=100.0, exit_price=70.0, quantity=25)
        assert pnl.gross_pnl == pytest.approx(-750.0)
        assert pnl.net_pnl < pnl.gross_pnl   # charges make loss bigger

    def test_net_pnl_pct_calculation(self):
        """Net P&L % should be relative to capital deployed."""
        pnl = calculate_net_pnl(entry_price=100.0, exit_price=130.0, quantity=25)
        capital_deployed = 100.0 * 25
        expected_pct = pnl.net_pnl / capital_deployed * 100
        assert abs(pnl.net_pnl_pct - expected_pct) < 0.01

    def test_charge_breakdown_keys(self):
        """charge_breakdown must contain all required keys."""
        pnl = calculate_net_pnl(100.0, 120.0, 25)
        required = {"stt", "nse_txn", "sebi_fee", "stamp_duty", "brokerage",
                    "gst", "total_charges", "gross_pnl", "net_pnl", "net_pnl_pct"}
        assert required.issubset(set(pnl.charge_breakdown.keys()))

    def test_breakeven_requires_charge_recovery(self):
        """Even if exit == entry, net P&L is negative (charges paid)."""
        pnl = calculate_net_pnl(entry_price=100.0, exit_price=100.0, quantity=25)
        assert pnl.gross_pnl == 0.0
        assert pnl.net_pnl < 0   # Charges were incurred

    def test_nifty_realistic_trade(self):
        """
        Realistic NIFTY option trade:
        Buy 1 lot (25 units) at ₹80 premium → sell at ₹110 (~37.5% gain)
        """
        pnl = calculate_net_pnl(entry_price=80.0, exit_price=110.0, quantity=25)
        gross     = (110 - 80) * 25   # = ₹750
        assert pnl.gross_pnl == pytest.approx(gross)
        assert pnl.total_charges < 100   # Charges should be small vs profit
        assert pnl.net_pnl > 650        # Net should be well above 0

    def test_banknifty_realistic_trade(self):
        """
        BankNifty 1 lot (15 units) at ₹200 → exit at ₹140 (loss scenario)
        """
        pnl = calculate_net_pnl(entry_price=200.0, exit_price=140.0, quantity=15)
        gross = (140 - 200) * 15   # = -₹900
        assert pnl.gross_pnl == pytest.approx(gross)
        assert pnl.net_pnl < gross   # More negative after charges


class TestDailySummary:
    """Test daily aggregation."""

    def test_empty_trades(self):
        result = daily_tax_summary([])
        assert result["trades"] == 0
        assert result["net_pnl"] == 0.0

    def test_multiple_trades_aggregation(self):
        trades = [
            {"entry_price": 100.0, "exit_price": 130.0, "quantity": 25},  # win
            {"entry_price": 150.0, "exit_price": 120.0, "quantity": 25},  # loss
            {"entry_price":  80.0, "exit_price": 100.0, "quantity": 25},  # win
        ]
        result = daily_tax_summary(trades)
        assert result["trades"] == 3
        assert result["winners"] == 2
        assert result["losers"]  == 1
        assert result["win_rate"] == pytest.approx(66.7, abs=0.1)
        assert isinstance(result["net_pnl"], float)

    def test_charges_always_positive(self):
        """Total charges must always be > 0 (never negative)."""
        trades = [{"entry_price": 100.0, "exit_price": 50.0, "quantity": 25}]
        result = daily_tax_summary(trades)
        assert result["total_charges"] > 0
