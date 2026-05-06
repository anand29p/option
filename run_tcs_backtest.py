#!/usr/bin/env python
"""Run backtests on TCS and generate reports."""

import sys
import json
from utils.backtester import run_backtest_pairs
from pathlib import Path

print("═" * 70)
print("STOCK OPTIONS BACKTEST: TCS (2-Signal & 3-Signal)")
print("═" * 70)
print()

log_dir = Path("logs")

try:
    print("1️⃣  Running 2-signal backtests on TCS...")
    results_2 = run_backtest_pairs(symbol='TCS', days=100, signal_count=2)
    print("   ✓ 2-signal backtest completed\n")
except Exception as e:
    print(f"   ✗ Error: {e}\n")
    sys.exit(1)

try:
    print("2️⃣  Running 3-signal backtests on TCS...")
    results_3 = run_backtest_pairs(symbol='TCS', days=100, signal_count=3)
    print("   ✓ 3-signal backtest completed\n")
except Exception as e:
    print(f"   ✗ Error: {e}\n")
    sys.exit(1)

print("═" * 70)
print("RESULTS SUMMARY")
print("═" * 70)

# Check what reports were generated
for file in ["backtest_report.html", "backtest_results.csv", "backtest_trades.csv"]:
    path = log_dir / file
    if path.exists():
        size_kb = path.stat().st_size / 1024
        print(f"✓ {file:30} ({size_kb:6.1f} KB)")

print()
print("Reports available in: logs/")
print("  - backtest_report.html       (open in browser)")
print("  - backtest_results.csv       (summary metrics)")
print("  - backtest_trades.csv        (all trades with P&L)")
print()
print("═" * 70)
