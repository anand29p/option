# STRATEGIES.md — Trading Strategies Documentation

## Overview

The bot uses three complementary option buying strategies, auto-selected based on market conditions. All are **long-only** (buy CE or PE) — no selling/writing.

---

## 1. 📈 Scalp Momentum (`strategies/scalp_momentum.py`)

**Best for:** High VIX (>14), trending markets, 9:30 AM–2:30 PM

### Logic
1. RSI(9) rises from oversold (<40) → **BUY CE** (bullish momentum)
2. RSI(9) falls from overbought (>60) → **BUY PE** (bearish momentum)
3. Confirmation: Price must be on correct side of VWAP
4. Volume must be 1.5× the 20-period average

### Parameters
| Parameter | Value | File |
|-----------|-------|------|
| RSI Period | 9 | settings.py |
| RSI Oversold | 35 | settings.py |
| RSI Overbought | 65 | settings.py |
| VWAP Buffer | 0.1% | settings.py |

### Trade Profile
- Timeframe: 1-min candles
- Avg holding: 5–20 minutes
- Target: 20–30% premium gain
- Stop-loss: 30% premium loss
- Frequency: 3–8 signals/day

---

## 2. 📊 ORB Breakout (`strategies/orb_breakout.py`)

**Best for:** Trending days, first 30 minutes of session

### Logic
1. Observe price action in first 15 minutes (9:15–9:30)
2. Store the **Opening Range**: high and low of that period
3. On breakout above range (+ 0.2% buffer) → **BUY CE**
4. On breakdown below range (- 0.2% buffer) → **BUY PE**
5. Trade only **ONCE per index per day** (high conviction)

### Parameters
| Parameter | Value | File |
|-----------|-------|------|
| ORB Duration | 15 min | settings.py |
| Breakout Buffer | 0.2% | settings.py |

### Trade Profile
- Timeframe: 15-min opening range
- Avg holding: 30–90 minutes
- Target: 30–50% premium gain
- Stop-loss: 30% premium loss
- Frequency: 1 signal/index/day (max 3 total)

---

## 3. 🔄 Mean Reversion (`strategies/mean_reversion.py`)

**Best for:** Low VIX (<14), sideways/rangebound markets

### Logic
1. Bollinger Bands(20, 2) squeeze detected (band width < 0.5%)
2. Price touches **lower band** + RSI < 38 → **BUY CE** (bounce expected)
3. Price touches **upper band** + RSI > 62 → **BUY PE** (pullback expected)

### Parameters
| Parameter | Value | File |
|-----------|-------|------|
| BB Period | 20 | settings.py |
| BB Std Dev | 2.0 | settings.py |
| Squeeze Threshold | 0.5% | settings.py |

### Trade Profile
- Timeframe: 5-min candles
- Avg holding: 15–45 minutes
- Target: 10–20% premium gain (smaller but safer)
- Stop-loss: 30% premium loss
- Frequency: 2–4 signals/day

---

## 🤖 Strategy Auto-Selection Logic

```
Time: 9:15–9:30 AM           → ORB Breakout (always first)
VIX ≥ 18 + Trending           → Scalp Momentum (aggressive)
14 ≤ VIX < 18 + Trending      → Scalp Momentum (conservative)
VIX < 14 or Sideways          → Mean Reversion
Time ≥ 3:00 PM                → No new trades
```

Trend is detected via EMA(9) vs EMA(21) slope on 1-min data.

---

## 🎯 Option Selection Rules

For each signal, the bot selects the option to buy using:

| Rule | Value | Reason |
|------|-------|--------|
| Expiry | Nearest weekly | Highest liquidity, faster premium movement |
| Strike | ATM or ATM±1 | Optimal delta exposure |
| Max Premium | ₹3,000 / lot_size | Within capital limits |
| Min OI | 500 contracts | Avoids illiquid strikes |
| Max Spread | 5% of LTP | Minimizes slippage |

---

## ⚠️ Risk Management

- **Stop-loss:** 30% loss on premium → auto exit
- **Target:** 20% gain → exit (conservative), trail beyond that
- **Max trades:** 2 simultaneous open positions
- **Daily loss limit:** ₹2,000 → all trading stops for the day
- **EOD square-off:** All positions closed by 3:15 PM (no overnight)
- **Capital per trade:** Max ₹3,000

---

## 📈 Expected Performance (Paper Trade Estimate)

| Metric | Estimate |
|--------|----------|
| Daily trades | 3–8 |
| Win rate | 45–55% (options buying is hard) |
| Avg winner | +₹150–₹400 net |
| Avg loser | −₹150–₹250 net |
| Breakeven trades needed | ~2 wins per 3 trades |
| Monthly target (optimistic) | +5–15% on ₹20,000 |

> **Note:** Past performance of any strategy does not guarantee future results. These are estimates based on backtested conditions. Paper trade for at least 2–4 weeks before any live consideration.
