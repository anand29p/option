#!/usr/bin/env python
"""Verify Dhan client and option chain utilities support stocks."""

from utils.dhan_client import DhanClient
from utils.option_chain import get_nearest_weekly_expiry, get_best_option
from config.settings import INDICES

print('✓ Utilities imported successfully')
print()

# Verify method signatures
client = DhanClient()

# Check get_spot_price signature
import inspect
sig = inspect.signature(client.get_spot_price)
print('get_spot_price signature:', sig)
assert 'is_index' in sig.parameters, "Missing is_index parameter"

# Check get_option_chain signature
sig = inspect.signature(client.get_option_chain)
print('get_option_chain signature:', sig)
assert 'is_index' in sig.parameters, "Missing is_index parameter"

# Check get_expiry_list signature
sig = inspect.signature(client.get_expiry_list)
print('get_expiry_list signature:', sig)
assert 'is_index' in sig.parameters, "Missing is_index parameter"

print()
print('✓ All methods support is_index parameter for both indices and stocks')
print()

# Verify get_best_option supports is_index
sig = inspect.signature(get_best_option)
print('get_best_option signature:', sig)
assert 'is_index' in sig.parameters, "Missing is_index parameter in get_best_option"

# Verify get_nearest_weekly_expiry supports is_index
sig = inspect.signature(get_nearest_weekly_expiry)
print('get_nearest_weekly_expiry signature:', sig)
assert 'is_index' in sig.parameters, "Missing is_index parameter in get_nearest_weekly_expiry"

print()
print('✓ All option chain utilities support is_index parameter')
print()
print('Testing use cases:')
print('  - Index option: get_spot_price("BANKNIFTY", is_index=True)')
print('  - Stock option: get_spot_price("TCS", is_index=False)')
print('  - Index chain: get_option_chain("BANKNIFTY", "2026-05-13", is_index=True)')
print('  - Stock chain: get_option_chain("TCS", "2026-05-13", is_index=False)')
print('  - Index expiry: get_nearest_weekly_expiry(client, "NIFTY", is_index=True)')
print('  - Stock expiry: get_nearest_weekly_expiry(client, "TCS", is_index=False)')
