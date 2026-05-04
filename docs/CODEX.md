# CODEX.md — Coding Instructions for AI Agents (Codex / Copilot / Claude Code)

> This file tells an AI coding agent **exactly** how to work on this project.
> Read this entire file before writing or editing any code.

---

## 🧠 Project Summary

**What this is:** A fully autonomous options buying bot for Indian equity derivatives
(Nifty 50, Bank Nifty, Fin Nifty) using the Zerodha Kite Connect API.

**Mode:** Paper trade only (virtual ₹20,000 capital). No real orders.

**Key constraint:** The bot must run completely hands-free during market hours
(9:15 AM – 3:25 PM IST). Never ask the user anything at runtime.

---

## 📂 File Map & Responsibilities

```
main.py                        Entry point. CLI only. Wires everything together.
config/settings.py             ALL parameters live here. Never hardcode elsewhere.
config/logging_config.py       Loguru setup. Call setup_logging() once at start.
utils/kite_client.py           Zerodha API wrapper. All API calls go through here.
utils/paper_engine.py          Virtual portfolio. Entry/exit/monitor/squareoff.
utils/option_chain.py          Finds best option to buy for a given signal.
utils/indicators.py            Technical indicator wrappers (pandas-ta).
utils/risk_manager.py          Pre-trade checks and position sizing.
utils/scheduler.py             APScheduler jobs. Controls timing of all bot jobs.
strategies/scalp_momentum.py   RSI + VWAP scalp on 1-min candles.
strategies/orb_breakout.py     Opening range breakout on 15-min range.
strategies/mean_reversion.py   Bollinger band squeeze on 5-min candles.
strategies/strategy_selector.py Auto-picks strategy. Calls run_cycle() on each index.
reports/daily_report.py        Daily P&L report with full tax breakdown.
reports/weekly_report.py       Weekly summary. Runs on Fridays automatically.
utils/tax_calculator.py        Computes STT, brokerage, GST etc. on every trade.
tests/test_tax_calculator.py   Pytest tests for tax logic.
```

---

## ✅ Coding Rules (Must Follow)

### 1. All configuration in `config/settings.py`
```python
# CORRECT — read from settings
from config.settings import STOP_LOSS_PCT
stop = entry_price * (1 - STOP_LOSS_PCT)

# WRONG — never hardcode
stop = entry_price * 0.70
```

### 2. All logging via `loguru`, never `print`
```python
from loguru import logger
logger.info("Trade entered")    # ✅
logger.debug("RSI value: 42")  # ✅
print("Trade entered")          # ❌ never
```

### 3. All timestamps in IST with tzinfo
```python
from config.settings import IST
from datetime import datetime
now = datetime.now(IST)         # ✅ always timezone-aware
now = datetime.now()            # ❌ never naive datetime
```

### 4. All money values are `float`, 2 decimal places in display
```python
capital = 20000.0               # ✅ float
capital = 20000                 # ❌ don't use int for money
f"₹{value:.2f}"                 # ✅ display format
```

### 5. Tax calculation on EVERY closed trade
```python
# In paper_engine.py exit_trade():
from utils.tax_calculator import calculate_net_pnl
pnl = calculate_net_pnl(entry_price, exit_price, quantity)
# NEVER skip this step
```

### 6. Never place real orders in paper mode
```python
from config.settings import MODE
if MODE == "live":
    kite.place_order(...)       # ✅ only in live mode
else:
    paper_engine.enter_trade(...)  # ✅ paper simulation
```

### 7. Wrap all Kite API calls in try/except
```python
try:
    data = kite.ltp(["NSE:NIFTY 50"])
except Exception as e:
    logger.error(f"LTP fetch failed: {e}")
    return None                 # Never crash the bot on API failure
```

### 8. Strategy files must NOT call the Kite API directly
```python
# strategies/scalp_momentum.py
# WRONG — strategy fetching data directly
data = kite.historical_data(...)

# CORRECT — strategy receives pre-fetched DataFrame
def generate_signal(self, index: str, df: pd.DataFrame) -> str:
    ...
```
Data fetching is done in `main.py → AlgoBot.run_cycle()` and passed in.

### 9. `generate_signal()` returns only string constants
```python
# Every strategy's generate_signal must return exactly one of:
return "BUY_CE"
return "BUY_PE"
return "NONE"
# Nothing else. No booleans, no dicts.
```

### 10. `execute()` is silent on NONE signals
```python
def execute(self, index, signal, spot_price):
    if signal == "NONE":
        return               # ✅ silent return, no log spam
```

---

## 🔌 How to Extend (Add a New Strategy)

1. Create `strategies/my_strategy.py` with this structure:
```python
class MyStrategy:
    NAME = "MyStrategy"

    def __init__(self, kite, paper_engine):
        self.kite   = kite
        self.engine = paper_engine

    def generate_signal(self, index: str, df: pd.DataFrame) -> str:
        # Your logic here
        return "BUY_CE" | "BUY_PE" | "NONE"

    def execute(self, index: str, signal: str, spot_price: float):
        if signal == "NONE":
            return
        # call self.engine.enter_trade(...)
```

2. Import and register in `strategies/strategy_selector.py`:
```python
from strategies.my_strategy import MyStrategy
self.my_strat = MyStrategy(kite, paper_engine)
```

3. Add selection logic in `StrategySelector.select()`.

4. Call in `StrategySelector.run_cycle()`.

---

## 🔌 How to Extend (Add a New Indicator)

Add a function to `utils/indicators.py`:
```python
def my_indicator(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Brief docstring."""
    return ta.some_function(df["close"], length=period)
```

Then import in the strategy:
```python
from utils.indicators import my_indicator
```

---

## 🧾 Tax Calculation — How It Works

Every closed trade MUST call `calculate_net_pnl()`:

```python
from utils.tax_calculator import calculate_net_pnl

pnl = calculate_net_pnl(
    entry_price = 100.0,   # Premium paid per unit
    exit_price  = 130.0,   # Premium received per unit
    quantity    = 25,      # lots × lot_size
)

print(pnl.net_pnl)                        # Net profit after ALL charges
print(pnl.charge_breakdown["stt"])        # STT paid
print(pnl.charge_breakdown["brokerage"]) # Brokerage paid
print(pnl.charge_breakdown["total_charges"])  # Sum of all charges
```

Charges deducted per trade (FY 2024-25):
- STT: 0.1% of premium on buy leg only
- NSE Transaction Charge: 0.053% both legs
- Stamp Duty: 0.003% on buy leg only
- SEBI Fee: ₹10 per crore of turnover
- Brokerage: ₹20 flat per order (both entry + exit = ₹40 total)
- GST: 18% on (brokerage + NSE charge), both legs

---

## 📅 Scheduler — Job Timing

| Job | Time (IST) | Frequency |
|-----|-----------|-----------|
| `pre_market()` | 9:00 AM | Daily |
| `run_cycle()` | 9:15–3:00 PM | Every 1 min |
| `monitor()` | 9:15–3:25 PM | Every 1 min |
| `squareoff_all()` | 3:15 PM | Daily |
| `daily_report()` | 3:30 PM | Daily |
| `weekly_report()` | 3:30 PM Fri | Weekly |

All times in `Asia/Kolkata`. Bot skips weekends and NSE holidays
(see `scheduler.py → MARKET_HOLIDAYS_2025`).

---

## 🗂️ Data Flow

```
KiteClient.get_historical()
        ↓
AlgoBot.run_cycle()  ← called every minute by scheduler
        ↓
StrategySelector.run_cycle(index, spot, vix, df_1min, df_5min)
        ↓
Strategy.generate_signal(index, df) → "BUY_CE" | "BUY_PE" | "NONE"
        ↓
Strategy.execute(index, signal, spot_price)
        ↓
OptionChain.get_best_option(kite, index, spot, option_type, max_premium)
        ↓
RiskManager.pre_trade_check(premium, quantity)  ← gate
        ↓
PaperEngine.enter_trade(symbol, index, option_type, ...)
        ↓ (position stored in open_trades dict)
PaperEngine.monitor_positions()  ← every minute checks SL/Target
        ↓ (on SL or target hit)
PaperEngine.exit_trade(trade_id, reason)
        ↓
TaxCalculator.calculate_net_pnl(entry, exit, qty)
        ↓
CSV trade log → daily_report → weekly_report
```

---

## 🧪 Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run only tax tests
pytest tests/test_tax_calculator.py -v

# With coverage
pytest tests/ --cov=utils --cov-report=term-missing
```

Tests must pass before any PR or deploy.

---

## 🚀 Running the Bot

```bash
# Install
pip install -r requirements.txt

# First-time Zerodha login (opens browser, run once per day)
python -c "from utils.kite_client import KiteClient; KiteClient()"

# Run paper trading bot (autonomous, runs until market close)
python main.py --mode paper

# Generate today's report manually
python main.py --report

# Generate weekly report manually
python main.py --weekly

# Stop the bot
Ctrl+C   # Triggers graceful shutdown + squareoff + report
```

---

## ⚠️ Common Pitfalls to Avoid

| Pitfall | Fix |
|---------|-----|
| Using naive datetime | Always use `datetime.now(IST)` |
| Crashing on Kite API error | Wrap in try/except, return None |
| Holding positions overnight | EOD squareoff at 3:15 PM is mandatory |
| Adding new parameters inline | Add to `config/settings.py` first |
| Skipping tax deduction on exit | Always call `calculate_net_pnl()` |
| Logging with print() | Use `logger.info/debug/error()` |
| Trading after 3:00 PM | Check time in scheduler, blocked by design |
| Deep OTM options (cheap premium) | Enforced by `DELTA_MIN=0.25` and OI check |

---

## 🔐 Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `KITE_API_KEY` | ✅ | — | Zerodha API key |
| `KITE_API_SECRET` | ✅ | — | Zerodha API secret |
| `MODE` | ❌ | `paper` | `paper` or `live` |

Set in `.env` file (never commit to git).

---

## 📦 Key Dependencies

| Package | Purpose |
|---------|---------|
| `kiteconnect` | Zerodha Kite API SDK |
| `pandas` | OHLCV data manipulation |
| `pandas-ta` | Technical indicators |
| `APScheduler` | Cron-style job scheduling |
| `loguru` | Structured logging |
| `rich` | Pretty console output |
| `python-dotenv` | Load .env config |
| `tinydb` | Lightweight JSON trade store |
| `pytest` | Unit testing |
