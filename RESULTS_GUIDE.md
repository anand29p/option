# 📊 Where to Find Backtest Results

## Results Files Location
All backtest results are saved to the `logs/` directory:

### 2-Signal Pair Backtest Results
```
logs/backtest_strategy_pairs_2signal_100d_YYYYMMDD.csv   ← CSV format (spreadsheet)
logs/backtest_strategy_pairs_2signal_100d_YYYYMMDD.html  ← HTML format (browser)
logs/backtest_strategy_pairs_2signal_100d_demo.html      ← Demo example (no backtest needed)
```

### 3-Signal Triplet Backtest Results
```
logs/backtest_strategy_pairs_3signal_100d_YYYYMMDD.csv   ← CSV format (spreadsheet)
logs/backtest_strategy_pairs_3signal_100d_YYYYMMDD.html  ← HTML format (browser)
logs/backtest_strategy_pairs_3signal_100d_demo.html      ← Demo example (no backtest needed)
```

---

## 🔍 How to View Results

### Option 1: HTML Reports (Recommended)
**Best for**: Quick visual review, easy comparison, professional presentation

1. Navigate to `logs/` folder
2. Find `backtest_strategy_pairs_*.html` file
3. Right-click → "Open with" → Browser (Chrome, Edge, Firefox, Safari)
4. View styled table with color-coded P&L, hover effects

**Features**:
- ✅ Dark theme (easy on eyes)
- ✅ Color-coded P&L (green=profit, red=loss)
- ✅ Sorted by best performers
- ✅ All metrics in one readable table
- ✅ Interpretation guide included

**Preview Demo**: See pre-generated demo HTML files
- `logs/backtest_strategy_pairs_2signal_100d_demo.html`
- `logs/backtest_strategy_pairs_3signal_100d_demo.html`

### Option 2: CSV Files
**Best for**: Data analysis, importing to Excel/Sheets, custom calculations

1. Navigate to `logs/` folder
2. Right-click `backtest_strategy_pairs_*.csv`
3. Open with Excel, Google Sheets, or any spreadsheet app
4. Sort/filter/chart as needed

**Columns Available**:
- `pair_name` - Strategy combination (e.g., RSI+VWAP)
- `index` - Index traded (BANKNIFTY)
- `100_day_net_pnl` - Total profit after charges
- `win_rate` - % of winning trades
- `trade_count` - Number of trades taken
- `profit_factor` - Gross wins / Gross losses
- `max_drawdown` - Largest loss peak-to-trough
- `avg_win` - Average profit per winning trade
- `avg_loss` - Average loss per losing trade
- `total_charges` - Total STT + brokerage + GST + stamp duty

---

## 🚀 How to Run Backtests and Generate Reports

### Run 2-Signal Backtests
```bash
python main.py --backtest-pairs 2
```
**Output** (automatically generated):
- CSV: `logs/backtest_strategy_pairs_2signal_100d_20260506.csv`
- HTML: `logs/backtest_strategy_pairs_2signal_100d_20260506.html`
- Console: Rich table summary

### Run 3-Signal Backtests
```bash
python main.py --backtest-pairs 3
```
**Output** (automatically generated):
- CSV: `logs/backtest_strategy_pairs_3signal_100d_20260506.csv`
- HTML: `logs/backtest_strategy_pairs_3signal_100d_20260506.html`
- Console: Rich table summary

---

## 📋 Interpreting the Reports

### HTML Table Columns

| Column | What It Means | What's Good |
|--------|--------------|-----------|
| **Pair Name** | Which 2-3 strategies were combined | N/A (just identifier) |
| **Index** | Market (BANKNIFTY in these tests) | BANKNIFTY |
| **Trades** | How many times all strategies agreed | More = more signal agreement |
| **Win Rate** | % of profitable trades | >60% is excellent |
| **Gross P&L** | Profit before deducting charges | Higher is better |
| **Charges** | STT, brokerage, GST, stamp duty | Lower is better (costs) |
| **Net P&L** | **Final profit (Gross - Charges)** | **This is your actual P&L** |
| **Max DD** | Biggest loss during period | Lower is better (less volatile) |
| **Profit Factor** | Gross Wins / Gross Losses | >1.3 is strong |
| **Avg Win** | Average profit per win | Shows win size |
| **Avg Loss** | Average loss per losing trade | Shows loss size |

### Green vs Red Coloring
- 🟢 **Green**: Positive P&L (profitable combination)
- 🔴 **Red**: Negative P&L (losing combination)

### Reading Strategy Combinations
Example: `RSIDivergence+VWAPReversion`
- Means: **Only take trades when BOTH RSI divergence AND VWAP reversion signal in the SAME direction**
- "+" = AND (both must agree)
- More strategies = more selective (fewer trades, potentially better quality)

---

## 💡 Example: How to Use Results

### Scenario: Comparing 2-Signal vs 3-Signal
**2-Signal Results** (more signal opportunities):
- 38 trades on RSI+VWAP combination
- 64.5% win rate
- +₹21,445 net P&L

**3-Signal Results** (more selective):
- 12 trades on RSI+VWAP+ORB combination
- 75% win rate
- +₹26,657 net P&L (higher!)

**Interpretation**: While 3-signal has fewer trades (12 vs 38), it has:
- Higher win rate (75% vs 64.5%)
- Higher total profit (₹26,657 vs ₹21,445)
- Better quality signals (when all 3 agree, setup is stronger)

### Scenario: Selecting Best Pair for Live Trading
1. Open HTML report
2. Look at **Net P&L** column (sorted descending)
3. Top row = best performer
4. Check win rate (should be >55% minimum)
5. Check max drawdown (should match your risk tolerance)
6. Select top 2-3 pairs to monitor live

---

## ⚙️ Technical Notes

### Files Generated
When you run `python main.py --backtest-pairs N`:

1. **CSV file** - Tab-separated values for data analysis
   - One header row + N result rows
   - Easily importable to Excel/Sheets/Python

2. **HTML file** - Styled report for viewing
   - Self-contained (all CSS embedded)
   - Dark theme with color coding
   - Mobile-friendly responsive table

3. **Console output** - Rich table printed to terminal
   - Same data as HTML but text-based
   - Useful for quick verification

### Timestamp
Files are timestamped with `YYYYMMDD`:
- `backtest_strategy_pairs_2signal_100d_20260506.csv`
- Different dates = different run dates
- Helps you track historical results

### Data Requirements
- Backtest uses last **100 trading days** by default
- Requires OHLCV data from either:
  - Local recorded data (from MarketDataRecorder)
  - Dhan API (auto-fallback if local unavailable)
  - Will show error if neither available

---

## 🎯 Quick Links

| Want To | Go To |
|---------|-------|
| See demo 2-signal HTML | `logs/backtest_strategy_pairs_2signal_100d_demo.html` |
| See demo 3-signal HTML | `logs/backtest_strategy_pairs_3signal_100d_demo.html` |
| Read implementation details | [IMPLEMENTATION.md](./IMPLEMENTATION.md) |
| Run backtests yourself | `python main.py --backtest-pairs 2` or `3` |
| View individual trades | `logs/backtest_trades.csv` (full backtest) |
| Compare all strategies | `logs/backtest_report.html` (standard backtest) |

---

**Last Updated**: 2026-05-06 | All results in `logs/` directory
