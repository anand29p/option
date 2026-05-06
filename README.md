# 🤖 NiftyBot — Autonomous Options Trading Bot

> **Zero platform fee** algo trading bot for NSE weekly options.  
> Migrated from Zerodha Kite → **Dhan API (Free)**.  
> Runs paper trading autonomously 9:15 AM – 3:15 PM IST with a live web dashboard.

---

## ✨ Features

| Feature | Detail |
|---|---|
| **Broker** | Dhan API — completely free, no monthly fees |
| **Instruments** | NIFTY · BANKNIFTY · FINNIFTY weekly options |
| **Strategies** | ORB, Mean Reversion, VWAP, EMA Crossover, RSI Divergence, SuperTrend, Gap & Go |
| **Risk Controls** | Daily loss limit · Max simultaneous trades · Trailing stop-loss |
| **Global Context** | GIFT Nifty · Dow · Nasdaq · Nikkei · Hang Seng · Crude Oil via yfinance |
| **News Sentiment** | ET Markets · Moneycontrol · Business Standard RSS + VADER NLP |
| **Dashboard** | Live web UI at `http://localhost:5000` — P&L curve, positions, global markets |
| **Trade Journal** | Every trade logged to TinyDB + CSV with full charge breakdown (STT, GST, brokerage) |
| **Backtesting** | Historical strategy validation via `--backtest` CLI flag |

---

## 🚀 Quick Start

### 1. Clone & Setup Environment

```bash
git clone <your-repo>
cd option

# Create conda environment (Python 3.12)
conda create -n option_bot_312 python=3.12
conda activate option_bot_312

# Install dependencies
pip install -r requirements.txt

# Download VADER sentiment data (one-time)
python -c "import nltk; nltk.download('vader_lexicon')"
```

### 2. Get Dhan API Credentials (Free)

1. Open a free account at **[dhan.co](https://dhan.co)**
2. Visit **[dhanhq.co/docs/v2/](https://dhanhq.co/docs/v2/)** → Generate Access Token
3. Copy your **Client ID** and **Access Token**

### 3. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env`:
```env
MODE=paper
DHAN_CLIENT_ID=your_client_id_here
DHAN_ACCESS_TOKEN=your_access_token_here
```

> ⚠️ Access tokens expire monthly. Regenerate at [api.dhan.co](https://api.dhan.co) each month.

### 4. Run the Bot

```bash
# Start paper trading (opens dashboard at http://localhost:5000)
python main.py

# Or explicitly specify mode
python main.py --mode paper
```

---

## 🖥️ Dashboard

The live web dashboard starts automatically at **[http://localhost:5000](http://localhost:5000)**

| Panel | What it shows |
|---|---|
| **Stats Bar** | Capital · Day P&L · Open positions · Total trades |
| **P&L Curve** | Cumulative net P&L across all sessions (Chart.js) |
| **News Sentiment** | Live Indian market sentiment from 3 RSS feeds + VADER NLP score |
| **Global Markets** | GIFT Nifty · Dow · S&P 500 · Nasdaq · Nikkei · Hang Seng · DAX · Crude · USD/INR |
| **Open Positions** | Live unrealized P&L, SL, target for each active trade |
| **Trade History** | Last 50 closed trades with net P&L after all charges |

Dashboard-only mode (no trading):
```bash
python main.py --dashboard
```

---

## 📋 CLI Commands

```bash
python main.py                  # Paper trade (default)
python main.py --mode paper     # Explicit paper mode
python main.py --report         # Print today's P&L report and exit
python main.py --weekly         # Print weekly summary and exit
python main.py --backtest       # Run historical backtest simulation (all strategies)
python main.py --backtest-pairs 2   # Backtest 2-signal pair combinations (100 days)
python main.py --backtest-pairs 3   # Backtest 3-signal triplet combinations (100 days)
python main.py --dashboard      # Start dashboard only (no trading)
```

### Pair-Specific Backtest Examples

**Problem**: Single strategy signals too noisy. Solution: Only trade when **multiple strategies agree**.

```bash
# Test 2-signal combinations (e.g., RSIDivergence + VWAPReversion must both signal)
python main.py --backtest-pairs 2
# Output → logs/backtest_strategy_pairs_2signal_100d_YYYYMMDD.csv (.html also generated)

# Test 3-signal triplets (more selective: all 3 must agree)
python main.py --backtest-pairs 3
# Output → logs/backtest_strategy_pairs_3signal_100d_YYYYMMDD.csv (.html also generated)
```

**View Results**:
- **CSV Format**: Open with Excel/Google Sheets for data analysis
  ```
  logs/backtest_strategy_pairs_2signal_100d_YYYYMMDD.csv
  logs/backtest_strategy_pairs_3signal_100d_YYYYMMDD.csv
  ```

- **HTML Format** (recommended for visual review): Open in any browser
  ```
  logs/backtest_strategy_pairs_2signal_100d_YYYYMMDD.html
  logs/backtest_strategy_pairs_3signal_100d_YYYYMMDD.html
  ```

- **Demo Examples** (to see format without running backtest):
  ```
  logs/backtest_strategy_pairs_2signal_100d_demo.html  ← 2-signal demo
  logs/backtest_strategy_pairs_3signal_100d_demo.html  ← 3-signal demo
  ```

**Pair Combinations Tested** (BANKNIFTY, 100 days):

2-Signal (6 pairs):
- RSIDivergence + VWAPReversion
- RSIDivergence + ORBBreakout
- RSIDivergence + MeanReversion
- VWAPReversion + ORBBreakout
- VWAPReversion + MeanReversion
- ORBBreakout + MeanReversion

3-Signal (4 triplets):
- RSIDivergence + VWAPReversion + ORBBreakout
- RSIDivergence + VWAPReversion + MeanReversion
- RSIDivergence + ORBBreakout + MeanReversion
- VWAPReversion + ORBBreakout + MeanReversion

**CSV Output Format**:
```
pair_name,index,100_day_net_pnl,win_rate,trade_count,profit_factor,max_drawdown,avg_win,avg_loss,total_charges
RSIDivergence+VWAPReversion,BANKNIFTY,21445.32,64.5,38,1.45,12389.65,1842.15,-1923.44,2156.89
```

See [IMPLEMENTATION.md](./IMPLEMENTATION.md) for detailed strategy logic.

---

## 🌍 Global Market Context

The bot fetches global indices every 5 minutes via **yfinance** (free, no API key):

| Symbol | Represents |
|---|---|
| `^NSEI` | GIFT Nifty / Nifty Spot (pre-market indicator) |
| `^DJI`  | Dow Jones Industrial Average |
| `^GSPC` | S&P 500 |
| `^IXIC` | Nasdaq Composite |
| `^N225` | Nikkei 225 |
| `^HSI`  | Hang Seng Index |
| `^GDAXI`| DAX (Germany) |
| `^FTSE` | FTSE 100 (UK) |
| `CL=F`  | Crude Oil Futures |
| `INR=X` | USD/INR Exchange Rate |

**How it's used:** If US closed >0.3% up AND Asia opened positive, the StrategySelector biases toward CE (bullish) options.

---

## 📰 News Sentiment

Sources (all free RSS, no API key):
- 📰 Economic Times Markets
- 📰 Moneycontrol Market Reports
- 📰 Business Standard Markets

Scored using **VADER** (NLTK) + custom financial keyword boosting.  
Scale: `-1.0` (very bearish) → `+1.0` (very bullish).

**Optional upgrade:** Add `ALPHA_VANTAGE_KEY` in `.env` for their dedicated  
News Sentiment API (25 free req/day, more accurate for Indian stocks).

---

## 📁 Project Structure

```
option/
├── main.py                    # CLI entry point
├── config/
│   ├── settings.py            # All configuration constants
│   └── logging_config.py      # Loguru setup
├── strategies/
│   ├── strategy_selector.py   # Picks best strategy per cycle
│   ├── orb_breakout.py        # Opening Range Breakout
│   ├── mean_reversion.py      # Bollinger Band mean reversion
│   ├── vwap_reversion.py      # VWAP touch-and-bounce
│   ├── ema_crossover.py       # EMA 9/21 crossover
│   ├── rsi_divergence.py      # RSI oversold/overbought
│   ├── supertrend_momentum.py # SuperTrend direction
│   └── gap_and_go.py          # Gap-up/down continuation
├── utils/
│   ├── dhan_client.py         # Dhan API wrapper (replaces kite_client)
│   ├── paper_engine.py        # Virtual trade executor
│   ├── option_chain.py        # Best-option selector via Dhan option_chain()
│   ├── risk_manager.py        # Daily loss limits, position sizing
│   ├── global_context.py      # GIFT Nifty + international indices
│   ├── news_sentiment.py      # RSS news + VADER sentiment
│   ├── tax_calculator.py      # STT, brokerage, GST calculation
│   ├── trade_journal.py       # TinyDB trade log
│   ├── health_monitor.py      # API connectivity checks
│   ├── scheduler.py           # APScheduler for market hours
│   └── backtester.py          # Historical simulation
├── dashboard/
│   ├── app.py                 # Flask server
│   └── templates/index.html   # Modern dark-mode UI
├── reports/
│   └── daily_report.py        # Rich terminal P&L report
├── logs/
│   ├── paper_trades.json      # TinyDB trade journal
│   └── trades.csv             # CSV trade log (with charges)
├── .env                       # Your credentials (git-ignored)
├── .env.example               # Template
├── requirements.txt
├── README.md
└── TECHSTACK.md
```

---

## 📊 Strategy Logic

Each strategy returns a signal dict: `{"action": "BUY_CE"|"BUY_PE"|"WAIT", "confidence": 0.0–1.0}`

StrategySelector filters by:
1. **VIX gate** — skips if VIX > 25 (too volatile)
2. **Time gate** — no new entries after 14:30 IST
3. **Global context** — biases CE/PE based on overnight US/Asia moves
4. **News sentiment** — reduces position size in strongly bearish news

---

## 🔒 Risk Management

| Parameter | Default | Setting |
|---|---|---|
| Paper capital | ₹20,000 | `PAPER_CAPITAL` |
| Max simultaneous trades | 3 | `MAX_SIMULTANEOUS_TRADES` |
| Stop loss | 30% | `STOP_LOSS_PCT` |
| Min target | 40% | `TARGET_PCT_MIN` |
| Daily loss limit | ₹2,000 | `MAX_DAILY_LOSS` |

All figures are **net of charges** (STT + brokerage ₹20/order + GST 18% + stamp duty).

---

## 🔄 Monthly Token Refresh

Dhan access tokens expire after 30 days. To refresh:

1. Login to [api.dhan.co](https://api.dhan.co)
2. Generate a new Access Token
3. Update `DHAN_ACCESS_TOKEN` in your `.env`
4. Restart the bot

---

## ⚠️ Disclaimer

This software is for **educational and paper trading purposes only**.  
Past simulated performance does not guarantee future real-money results.  
Options trading involves substantial risk of loss.
