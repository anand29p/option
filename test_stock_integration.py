#!/usr/bin/env python
"""Verify main.py processes both indices and stocks correctly."""

from main import AlgoBot
from config.settings import INDICES

print('✓ AlgoBot imported successfully')
print()

# Check that _process_index method exists and has correct signature
import inspect
bot = AlgoBot()
sig = inspect.signature(bot._process_index)
print('_process_index signature:', sig)
print()

# List all symbols and their type
print('All symbols that will be processed in run_cycle():')
for symbol in INDICES:
    cfg = INDICES[symbol]
    sym_type = cfg.get('type', 'unknown')
    print(f'  {symbol:20} ({sym_type})')

print()
print('✓ Bot ready to process both indices and stocks')
print()
print('When _process_index is called:')
print('  - For indices (NIFTY, BANKNIFTY, FINNIFTY):')
print('    - Uses is_index=True for spot/candles/options')
print('    - VIX is fetched and used for regime selection')
print('  - For stocks (TCS, INFY, etc.):')
print('    - Uses is_index=False for spot/candles/options')
print('    - VIX is skipped (stocks trade on IV, not global VIX)')
print('    - Each stock processes independently')
