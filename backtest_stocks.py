#!/usr/bin/env python
"""Run comprehensive backtests on high-liquidity NSE stocks."""

import sys
import json
from pathlib import Path
from utils.backtester import run_backtest_pairs

print("╔" + "═" * 72 + "╗")
print("║" + " STOCK OPTIONS BACKTEST SUITE ".center(72) + "║")
print("║" + " Running 2-Signal & 3-Signal Consensus ".center(72) + "║")
print("╚" + "═" * 72 + "╝")
print()

# High-liquidity stocks to test
test_symbols = [
    "TCS",           # IT major
    "INFY",          # IT major  
    "RELIANCE",      # Blue chip
]

log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

results_summary = {
    "timestamp": "",
    "stocks_tested": test_symbols,
    "tests_completed": [],
    "test_failures": [],
}

import datetime
results_summary["timestamp"] = datetime.datetime.now().isoformat()

for symbol in test_symbols:
    print(f"\n{'─' * 70}")
    print(f"Testing: {symbol}")
    print(f"{'─' * 70}")
    
    # Test 2-signal combinations
    print(f"\n📊 2-Signal Pairs on {symbol}...")
    try:
        run_backtest_pairs(days=100, signal_count=2, symbol=symbol)
        results_summary["tests_completed"].append(f"{symbol}:2-signal")
        print(f"   ✓ Completed")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
        results_summary["test_failures"].append({
            "symbol": symbol,
            "signal_count": 2,
            "error": str(e)
        })

    # Test 3-signal combinations  
    print(f"\n📊 3-Signal Triplets on {symbol}...")
    try:
        run_backtest_pairs(days=100, signal_count=3, symbol=symbol)
        results_summary["tests_completed"].append(f"{symbol}:3-signal")
        print(f"   ✓ Completed")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
        results_summary["test_failures"].append({
            "symbol": symbol,
            "signal_count": 3,
            "error": str(e)
        })

print()
print("╔" + "═" * 72 + "╗")
print("║" + " BACKTEST SUMMARY ".center(72) + "║")
print("╚" + "═" * 72 + "╝")
print()
print(f"✓ Tests completed: {len(results_summary['tests_completed'])}")
print(f"✗ Test failures:   {len(results_summary['test_failures'])}")
print()

# List generated reports
print("Generated Reports:")
for file in sorted(log_dir.glob("backtest*.html")):
    size_kb = file.stat().st_size / 1024
    print(f"  📄 {file.name:50} ({size_kb:6.1f} KB)")

print()
for file in sorted(log_dir.glob("backtest*.csv")):
    size_kb = file.stat().st_size / 1024
    print(f"  📄 {file.name:50} ({size_kb:6.1f} KB)")

print()
print("Location: logs/")
print()

# Save summary
summary_file = log_dir / "backtest_summary.json"
with open(summary_file, "w") as f:
    json.dump(results_summary, f, indent=2)
print(f"✓ Summary saved: {summary_file}")
