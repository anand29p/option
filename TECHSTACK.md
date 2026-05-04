# 🛠️ Tech Stack

## Core Language
| | |
|---|---|
| **Python** | 3.12 (via Conda environment `option_bot_312`) |

---

## Broker / Market Data

| Library | Version | Purpose |
|---|---|---|
| **dhanhq** | ≥ 2.2.0 | Dhan broker API — orders, live LTP, option chain, historical OHLCV |
| **yfinance** | latest | Free international market data — GIFT Nifty, Dow, Nasdaq, Nikkei, Hang Seng, Crude Oil, USD/INR |

> **Why Dhan?** Zero monthly platform fee (Zerodha charges ₹2,000/month for API access).  
> Dhan provides free API access to all account holders.

---

## Data & Analysis

| Library | Purpose |
|---|---|
| **pandas** ≥ 2.0 | OHLCV DataFrames, resampling (1min → 5min candles), strategy signal computation |
| **pandas-ta** | Technical indicators — Bollinger Bands, EMA, RSI, VWAP, SuperTrend, ATR |
| **numpy** | Numerical operations in strategy logic |

---

## News Sentiment

| Library | Purpose |
|---|---|
| **feedparser** | Parses RSS feeds from ET Markets, Moneycontrol, Business Standard (no auth needed) |
| **nltk** + VADER | Offline sentiment scoring on financial headlines. No API key. |

> **How it works:** Headlines fetched every 15 min from 3 Indian financial RSS feeds.  
> VADER compound score + custom financial keyword boosting (rally/crash/surge/drop etc.)  
> Result: BULLISH / NEUTRAL / BEARISH label used to bias strategy direction.

---

## Scheduling & Orchestration

| Library | Purpose |
|---|---|
| **APScheduler** ≥ 3.10 | Cron-style jobs — pre-market reset, every-minute cycle, EOD square-off, daily report |
| **click** ≥ 8.1 | CLI interface — `--mode`, `--report`, `--backtest`, `--dashboard` flags |

---

## Trade Persistence

| Library | Purpose |
|---|---|
| **tinydb** ≥ 4.8 | Lightweight embedded JSON database for trade journal (queryable across sessions) |
| **csv** (stdlib) | Flat-file trade log with full charge breakdown |

---

## Web Dashboard

| Library | Purpose |
|---|---|
| **Flask** ≥ 3.0 | Lightweight REST server serving the live dashboard UI |
| **Chart.js** 4.x | Client-side P&L curve chart (loaded from CDN) |
| **Vanilla CSS** | Custom dark-mode design system (no Tailwind/Bootstrap) |
| **Google Fonts** | Inter + JetBrains Mono typography |

Dashboard auto-refreshes every **5 seconds** via JavaScript `fetch()` polling.  
No WebSocket needed — Flask JSON endpoints are fast enough for trading data.

---

## Logging & Monitoring

| Library | Purpose |
|---|---|
| **loguru** ≥ 0.7 | Structured colored logging with automatic daily file rotation |
| **rich** ≥ 13.4 | Terminal P&L reports with colored tables and progress bars |

---

## Testing

| Library | Purpose |
|---|---|
| **pytest** ≥ 7.4 | Unit tests for all strategies and engine (27 tests, 100% pass rate) |

Run tests:
```bash
pytest tests/ -v
```

---

## Architecture Diagram

```
                        ┌─────────────────┐
                        │   main.py (CLI) │
                        └────────┬────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
    ┌─────────▼────────┐ ┌───────▼──────┐ ┌────────▼────────┐
    │  BotScheduler    │ │  AlgoBot     │ │ Flask Dashboard │
    │  (APScheduler)   │ │  Controller  │ │  :5000          │
    └─────────┬────────┘ └───────┬──────┘ └────────┬────────┘
              │                  │                  │
              │         ┌────────┴────────┐         │
              │         │                │         │
    ┌─────────▼──┐  ┌───▼───────┐  ┌────▼──────┐   │
    │DhanClient  │  │ Strategy  │  │ Paper     │◄──┘
    │(dhanhq v2) │  │ Selector  │  │ Engine    │
    └─────┬──────┘  └───┬───────┘  └────┬──────┘
          │             │               │
    ┌─────▼──────┐  ┌───▼──────────┐  ┌─▼────────────┐
    │ Option     │  │ Global       │  │ Risk Manager  │
    │ Chain      │  │ Context      │  │ + Tax Calc    │
    │ Selector   │  │ (yfinance)   │  └──────────────┘
    └────────────┘  └──────────────┘
                    ┌───────────────┐
                    │ News Sentiment│
                    │ (RSS + VADER) │
                    └───────────────┘
```

---

## Environment

```
OS:      Windows 10/11
Python:  3.12 (Conda)
Env:     option_bot_312
Market:  NSE India (9:15 AM – 3:30 PM IST)
Timezone: Asia/Kolkata (IST = UTC+5:30)
```

---

## Cost Comparison

| Platform | API Cost | Our Setup |
|---|---|---|
| Zerodha Kite Connect | ₹2,000/month | ❌ Replaced |
| **Dhan API** | **₹0/month** | ✅ Current |
| yfinance (global data) | **₹0** | ✅ Free |
| VADER Sentiment | **₹0** | ✅ Free/Offline |
| RSS News Feeds | **₹0** | ✅ Free |
| **Total** | **₹0/month** | 🎉 |
