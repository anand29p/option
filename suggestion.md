# Suggestion Guide (Recovery Notes)

This file captures all key guidance from our chat so you do not lose context.

## 1) Streamlit Deploy Basics

- Use the real app entry file, not placeholders.
- App file: streamlit_app.py
- Streamlit Cloud branch: main
- Python runtime: 3.12
- runtime.txt is added to enforce Python 3.12 in cloud builds.

## 2) Why deployment failed earlier

- Error "File does not exist: yourscript.py" happened because that is a placeholder name.
- "Unable to deploy" was due app/repo detection flow mismatch, not because your repo was missing.
- "Error installing requirements" was resolved by pinning Python 3.12.

## 3) Streamlit Cloud Advanced Settings (Secrets)

Secrets must be strict TOML key-value lines only.

Use this format:

```toml
MODE = "paper"
DHAN_CLIENT_ID = "<your_client_id>"
DHAN_ACCESS_TOKEN = "<your_access_token>"
PAPER_CAPITAL = "100000"
MAX_CAPITAL_PER_TRADE = "10000"
ACTIVE_STRATEGY_ALLOWLIST = "FINNIFTY:RSIDivergence"
SHADOW_SIGNAL_LOG = "true"
ALPHA_VANTAGE_KEY = "<optional>"
TWELVE_DATA_API_KEY = "<optional>"
```

Do not paste plain text notes in the secrets box unless they start with # comments.

## 4) Important runtime behavior

- streamlit_app.py is dashboard/UI.
- Autonomous trade/data loop runs from main.py scheduler.
- Free Streamlit tier can sleep when inactive.
- For always-on collection/trading, run main.py on an always-on machine/VPS.

## 5) Data capture and backtesting upgrades done

Implemented:

- Real option-chain snapshot capture from Dhan near ATM.
- ATM CE/PE premium time series logging.
- Backtester now prefers recorded ATM option premiums; falls back to simulated premium only when data is missing.

Generated files during runtime:

- logs/market_data/<INDEX>_1min.csv
- logs/market_data/<INDEX>_5min.csv
- logs/market_data/cycle_snapshots.csv
- logs/market_data/<INDEX>_options_near_atm.csv
- logs/market_data/<INDEX>_options_atm.csv

## 6) How to run now

### Local paper mode (data collection)

```bash
conda activate option_bot_312
python main.py --mode paper
```

### Backtest

```bash
python main.py --backtest
```

Longer window:

```bash
conda run -n option_bot_312 python -c "from utils.backtester import run_backtest; run_backtest(days=30)"
```

## 7) Data API purchase decision

If you are serious and want better research quality, Data API is useful.

- Trading API may be free.
- Data API is what improves reliable market/history access for serious backtesting workflows.

## 8) Access token is valid for 24 hours (important)

You must refresh Dhan access token daily.

Daily checklist:

1. Generate new access token in DhanHQ.
2. Update local .env:
   - DHAN_ACCESS_TOKEN=<new_token>
3. Update Streamlit Cloud Secrets:
   - DHAN_ACCESS_TOKEN = "<new_token>"
4. Reboot/redeploy Streamlit app (or restart local process) so new token is loaded.
5. Confirm app health by checking dashboard refresh and logs.

## 9) Security actions

- Previous token was exposed in screenshots/chat.
- Revoke/rotate token immediately.
- Never share tokens in screenshots, chat, or committed files.
- Keep .env out of git.

## 10) If something breaks

Quick triage order:

1. Confirm Python 3.12 runtime.
2. Confirm secrets TOML syntax.
3. Confirm valid fresh DHAN_ACCESS_TOKEN (not expired).
4. Check Streamlit Manage App logs for first failing package/error.
5. Reboot app after any secret/token change.

## 11) Optional next improvement

- Add an automated token freshness check at startup to fail fast with clear error message and reminder.
- Add a historical bulk downloader module for options data if you want larger backtest windows faster.
