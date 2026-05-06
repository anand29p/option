#!/usr/bin/env python
"""Verify stock options configuration is loaded correctly."""

from config.settings import INDICES, SECURITY_IDS

print('✓ Config loaded successfully')
print()
print('Instruments in INDICES:')
indices = [k for k, v in INDICES.items() if v.get('type') == 'index']
stocks = [k for k, v in INDICES.items() if v.get('type') == 'stock']
print(f'  - Indices: {len(indices)} ({", ".join(indices)})')
print(f'  - Stocks:  {len(stocks)}')
print(f'    {", ".join(stocks[:8])}')
if len(stocks) > 8:
    print(f'    (and {len(stocks)-8} more)')
print()
print(f'Security IDs defined: {len(SECURITY_IDS)}')
print()
print('Sample stock configuration:')
for symbol in stocks[:3]:
    cfg = INDICES[symbol]
    print(f'  {symbol}:')
    print(f'    lot_size={cfg["lot_size"]}, strike_step={cfg["strike_step"]}, type={cfg["type"]}')
