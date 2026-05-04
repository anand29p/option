# 🤖 Nifty Options Algo Trader — Paper Trading Bot

An **autonomous**, **fully automated** options buying bot for **Nifty 50**, **Bank Nifty**, and **Fin Nifty** using the **Zerodha Kite Connect API**. Runs in paper trade mode with a virtual capital of ₹20,000. No human intervention required during market hours.

---

## 📁 Project Structure

```
algo_trading/
├── README.md                    ← You are here
├── requirements.txt             ← Python dependencies
├── claude.md                    ← AI/LLM context file (optional)
├── .env.example                 ← Environment variable template
├── main.py                      ← Entry point — runs the bot
├── config/
│   ├── settings.py              ← All config: capital, risk, indices
│   └── logging_config.py        ← Logging setup
├── strategies/
│   ├── scalp_momentum.py        ← 1–5 min momentum scalp (primary)
│   ├── orb_breakout.py          ← Opening Range Breakout strategy
│   ├── mean_reversion.py        ← Short-term mean reversion
│   └── strategy_selector.py    ← Auto-picks best strategy per session
├── utils/
│   ├── kite_client.py           ← Zerodha Kite API wrapper
│   ├── option_chain.py          ← Option chain fetcher & analyzer
│   ├── indicators.py            ← RSI, VWAP, ATR, SuperTrend, etc.
│   ├── paper_engine.py          ← Paper trade execution engine
│   ├── risk_manager.py          ← Position sizing, stop-loss, capital guard
│   ├── tax_calculator.py        ← Indian STT, brokerage, GST, SEBI charges
│   └── scheduler.py             ← Market hours + session scheduler
├── reports/
│   ├── daily_report.py          ← P&L report generator (daily)
│   └── weekly_report.py         ← Weekly summary with tax breakdown
├── logs/                        ← Auto-generated trade logs (JSON + CSV)
└── tests/
    └── test_tax_calculator.py   ← Unit tests for tax logic
```

---

## ⚙️ Setup Instructions

### 1. Prerequisites
- Python **3.10+**
- Zerodha account with **Kite Connect API** subscription (₹2000/month or free for algo users)
- API Key and API Secret from [kite.trade](https://kite.trade)

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment
```bash
cp .env.example .env
# Edit .env with your Zerodha API credentials
```

### 4. First-Time Login (generates access token)
```bash
python utils/kite_client.py --login
```
This opens a browser, you log in once, and the token is cached for the day.

### 5. Run the Bot (Paper Mode)
```bash
python main.py --mode paper
```

The bot runs **fully autonomously** from 9:15 AM to 3:25 PM IST on trading days.

---

## 🧠 Strategies Used

| Strategy | Timeframe | When Used | Target |
|---|---|---|---|
| **Scalp Momentum** | 1–3 min | High volatility, trend days | 15–25% on option premium |
| **ORB Breakout** | 15 min | First hour breakout | 20–40% on option premium |
| **Mean Reversion** | 5 min | Sideways/rangebound market | 10–20% on option premium |

All strategies use **only option buying** (long calls/puts). No selling/writing.

---

## 💰 Capital & Risk Rules

| Parameter | Value |
|---|---|
| Total Paper Capital | ₹20,000 |
| Max capital per trade | ₹3,000 |
| Max simultaneous positions | 2 |
| Stop-loss per trade | 30% of premium paid |
| Target per trade | 20–40% of premium paid |
| Max daily loss | ₹2,000 (10%) → bot stops for the day |
| Instruments | Nifty, BankNifty, FinNifty (weekly options) |

---

## 🧾 Tax & Charges Calculation (Indian Markets)

All P&L is calculated **after deducting** the following charges on **each trade**:

| Charge | Rate |
|---|---|
| STT (Options Buy) | 0.1% of premium (on buy side only for option buyers, as of 2024 budget) |
| Exchange Transaction Charges | NSE: 0.053% of premium |
| SEBI Turnover Fee | ₹10 per crore of turnover |
| GST | 18% on (Brokerage + Transaction Charges) |
| Stamp Duty | 0.003% on buy side |
| Zerodha Brokerage | ₹20 per executed order (flat) |

> **Note:** STT rules for options were updated in Budget 2024. STT on option **buying** is 0.1% of premium. Verify latest rates at [zerodha.com/z-connect](https://zerodha.com/z-connect).

Weekly P&L reports include cumulative tax paid and net realized profit.

---

## 📊 Reports

- **Daily Report** → saved to `logs/YYYY-MM-DD_report.csv`
- **Weekly Report** → saved to `logs/week_YYYY-WNN_summary.json`
- Includes: gross P&L, total charges, net P&L, win rate, avg profit/loss per trade

---

## 🔐 Security Notes

- **Never commit your `.env` file**
- `.gitignore` excludes `.env`, `logs/`, and `__pycache__/`
- Access tokens expire daily and are auto-refreshed on login

---

## ⚠️ Disclaimer

This bot runs in **paper trade mode only** by default. It does **not** place real orders unless you explicitly switch `MODE=live` in `.env`. Even then, use at your own risk. Options trading involves substantial risk of loss.
