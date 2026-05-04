# claude.md — AI Context for Nifty Options Algo Trader

This file provides context for AI assistants (Claude, Copilot, etc.) working on this codebase.

## Project Purpose
Fully autonomous options buying bot for Indian equity derivatives (Nifty, BankNifty, FinNifty) via Zerodha Kite Connect API. Paper trading only with ₹20,000 virtual capital.

## Core Constraints
- **Only option BUYING** — no selling/writing, no futures
- **Paper trade mode** by default — `MODE=paper` in `.env`
- **Max ₹20,000** total virtual capital
- **Auto-pilot** — no human intervention during market hours
- **Indian tax-aware** — every P&L must deduct STT, brokerage, GST, stamp duty, SEBI fee
- **Risk-first** — stop-loss and daily loss limits are hard-coded and non-negotiable

## Key Files
- `config/settings.py` — single source of truth for all parameters
- `utils/paper_engine.py` — simulates order fills using live Kite quotes
- `utils/tax_calculator.py` — must be called on every closed trade
- `strategies/strategy_selector.py` — auto-selects strategy based on VIX, time of day, and trend

## Indian Market Hours (IST)
- Pre-open: 9:00–9:15 AM
- Market open: 9:15 AM
- No new positions after: 3:15 PM
- Market close: 3:30 PM
- All times in `Asia/Kolkata` timezone

## Options Logic Notes
- Use **weekly expiry** options for all three indices
- Strike selection: ATM ± 1 strike based on momentum signal
- Prefer options with delta 0.3–0.5 (not deep OTM)
- Avoid options with very low OI or wide bid-ask spreads (>5% of LTP)

## Tax Rules (FY 2024-25 onwards)
- STT on options buy: 0.1% of premium paid
- NSE transaction charge: 0.053% of premium
- Stamp duty: 0.003% of premium (buy side)
- SEBI turnover fee: ₹10 per crore
- Brokerage: ₹20 flat per order (Zerodha)
- GST: 18% on (brokerage + exchange transaction charge)

## Strategy Selection Logic
```
if VIX > 18 and time in [09:15-10:30]:
    use ORB Breakout
elif VIX > 14 and trending:
    use Scalp Momentum
else:
    use Mean Reversion
```

## Do NOT
- Place real orders unless `MODE=live` explicitly set
- Hold positions overnight (auto square-off at 3:15 PM)
- Use margin or leverage beyond buying premium
- Trade if daily loss > ₹2,000

## Style Guide
- All monetary values in Indian Rupees (₹), stored as `float` with 2 decimal places
- Timestamps always in IST (`Asia/Kolkata`), stored as `datetime` with tzinfo
- Log every trade decision with reason, even if no trade is placed
- Use `loguru` for all logging (not `print`)
