# config/settings.py
# ─────────────────────────────────────────────────────────────────────────────
# Single source of truth for ALL bot parameters.
# Change values here — never hardcode in strategy files.
# ─────────────────────────────────────────────────────────────────────────────

import os
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

load_dotenv()


def _load_streamlit_secrets_into_env() -> None:
    """Mirror Streamlit secrets into os.environ when running on Streamlit Cloud."""
    try:
        import streamlit as st
    except Exception:
        return

    try:
        for key in st.secrets:
            value = st.secrets[key]
            if isinstance(value, (str, int, float, bool)):
                os.environ.setdefault(key, str(value))
    except Exception:
        return


_load_streamlit_secrets_into_env()

# ── Timezone ──────────────────────────────────────────────────────────────────
IST = ZoneInfo("Asia/Kolkata")

# ── Mode ──────────────────────────────────────────────────────────────────────
MODE = os.getenv("MODE", "paper")          # "paper" | "live"
assert MODE in ("paper", "live"), "MODE must be 'paper' or 'live'"

# ── Zerodha → Dhan (Free API) ────────────────────────────────────────────────
# Get your free Client ID + Access Token at: https://api.dhan.co
DHAN_CLIENT_ID    = os.getenv("DHAN_CLIENT_ID",    "")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")

# Dhan security IDs (stable integer identifiers)
# Indices: hardcoded per Dhan docs
# Stocks: typically NSE:SYMBOL maps to unique integer; user can override in .env
INDEX_SECURITY_IDS = {
    # Indices (exchange segment: IDX_I)
    "NIFTY":     "13",
    "BANKNIFTY": "25",
    "FINNIFTY":  "27",
}

STOCK_SECURITY_IDS = {
    # NSE equities (exchange segment: NSE_EQ for spot, NSE_FNO for options)
    # These are approximate; will be overridden if Dhan API returns different values
    "TCS":       "2885",
    "INFY":      "356",
    "HDFC":      "13815",
    "HDFC BANK": "13781",
    "AXIS BANK": "13780",
    "ICICI BANK": "13785",
    "RELIANCE":  "13787",
    "HUL":       "13789",
    "LT":        "13814",
    "ITC":       "13793",
    "MARUTI":    "13818",
    "BAJAJ AUTO": "13747",
    "BHARTI AIRTEL": "13744",
    "WIPRO":     "13817",
    "COAL INDIA": "13759",
}

# Merge for lookups (prefer stock IDs, fallback to index IDs)
SECURITY_IDS = {**STOCK_SECURITY_IDS, **INDEX_SECURITY_IDS}

# ── Capital & Risk ────────────────────────────────────────────────────────────
PAPER_CAPITAL           = float(os.getenv("PAPER_CAPITAL", "100000"))   # ₹ Total virtual capital
MAX_CAPITAL_PER_TRADE   = float(os.getenv("MAX_CAPITAL_PER_TRADE", "10000"))   # ₹ Max premium outlay per trade
MAX_SIMULTANEOUS_TRADES = 2          # Open positions at any time
STOP_LOSS_PCT           = 0.30       # 30% loss on premium → exit
TARGET_PCT_MIN          = 0.20       # Minimum target: 20% gain
TARGET_PCT_MAX          = 0.40       # Stretch target: 40% gain
MAX_DAILY_LOSS          = 2_000.0   # ₹ Bot stops trading for the day
SQUAREOFF_TIME          = (15, 15)   # (hour, minute) IST — force exit

# ── Instruments ───────────────────────────────────────────────────────────────
# Includes both index options (VIX-aware) and equity options (top liquid stocks)
INDICES = {
    # Index options (highest liquidity + VIX integration)
    "NIFTY": {
        "symbol":       "NSE:NIFTY 50",
        "fut_symbol":   "NFO:NIFTY",
        "lot_size":     25,
        "strike_step":  50,
        "type":         "index",
    },
    "BANKNIFTY": {
        "symbol":       "NSE:NIFTY BANK",
        "fut_symbol":   "NFO:BANKNIFTY",
        "lot_size":     15,
        "strike_step":  100,
        "type":         "index",
    },
    "FINNIFTY": {
        "symbol":       "NSE:NIFTY FIN SERVICE",
        "fut_symbol":   "NFO:FINNIFTY",
        "lot_size":     25,
        "strike_step":  50,
        "type":         "index",
    },
    # Top liquid equity options (NSE)
    "TCS": {
        "symbol":       "NSE:TCS",
        "lot_size":     1,
        "strike_step":  5,
        "type":         "stock",
    },
    "INFY": {
        "symbol":       "NSE:INFY",
        "lot_size":     1,
        "strike_step":  5,
        "type":         "stock",
    },
    "HDFC BANK": {
        "symbol":       "NSE:HDFCBANK",
        "lot_size":     1,
        "strike_step":  5,
        "type":         "stock",
    },
    "AXIS BANK": {
        "symbol":       "NSE:AXISBANK",
        "lot_size":     1,
        "strike_step":  5,
        "type":         "stock",
    },
    "ICICI BANK": {
        "symbol":       "NSE:ICICIBANK",
        "lot_size":     1,
        "strike_step":  5,
        "type":         "stock",
    },
    "RELIANCE": {
        "symbol":       "NSE:RELIANCE",
        "lot_size":     1,
        "strike_step":  5,
        "type":         "stock",
    },
    "HUL": {
        "symbol":       "NSE:HUL",
        "lot_size":     1,
        "strike_step":  2,
        "type":         "stock",
    },
    "LT": {
        "symbol":       "NSE:LT",
        "lot_size":     1,
        "strike_step":  5,
        "type":         "stock",
    },
    "ITC": {
        "symbol":       "NSE:ITC",
        "lot_size":     1,
        "strike_step":  2,
        "type":         "stock",
    },
    "MARUTI": {
        "symbol":       "NSE:MARUTI",
        "lot_size":     1,
        "strike_step":  5,
        "type":         "stock",
    },
    "BAJAJ AUTO": {
        "symbol":       "NSE:BAJAJAUT",
        "lot_size":     1,
        "strike_step":  5,
        "type":         "stock",
    },
}

# ── Option Selection Rules ────────────────────────────────────────────────────
EXPIRY_TYPE             = "weekly"   # Always trade weekly expiry
MIN_OI                  = 500        # Minimum open interest (contracts)
MAX_SPREAD_PCT          = 0.05       # Max bid-ask spread as % of LTP (5%)
DELTA_MIN               = 0.25       # Minimum delta (avoid very deep OTM)
DELTA_MAX               = 0.55       # Maximum delta (avoid deep ITM)

# ── Strategy Parameters ───────────────────────────────────────────────────────
# Scalp Momentum
SCALP_RSI_PERIOD        = 9
SCALP_RSI_OVERBOUGHT    = 65
SCALP_RSI_OVERSOLD      = 35
SCALP_VWAP_BUFFER_PCT   = 0.001      # 0.1% above/below VWAP

# ORB Breakout
ORB_MINUTES             = 15         # Opening range = first 15 min candles
ORB_BUFFER_PCT          = 0.002      # 0.2% beyond range boundary

# Mean Reversion
MR_BOLLINGER_PERIOD     = 20
MR_BOLLINGER_STD        = 2.0
MR_MIN_SQUEEZE_PCT      = 0.005      # Band width < 0.5% of price

# VIX thresholds for strategy selection
VIX_HIGH                = 18.0
VIX_MEDIUM              = 14.0

# ── Tax & Charges (FY 2024-25) ────────────────────────────────────────────────
TAX = {
    "stt_buy_pct":          0.001,   # 0.1% of premium on buy
    "nse_txn_charge_pct":   0.00053, # 0.053% of premium
    "stamp_duty_pct":       0.00003, # 0.003% on buy side
    "sebi_fee_per_crore":   10.0,    # ₹10 per crore of turnover
    "brokerage_per_order":  20.0,    # ₹20 flat (Zerodha)
    "gst_pct":              0.18,    # 18% on brokerage + txn charge
}

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR     = "logs"
LOG_LEVEL   = "DEBUG"
TRADE_LOG   = f"{LOG_DIR}/trades.csv"
RUNTIME_STATUS_FILE = os.getenv("RUNTIME_STATUS_FILE", f"{LOG_DIR}/runtime_status.json")

# Strategy execution controls.
# Format: INDEX:StrategyName,INDEX:StrategyName
# Example: FINNIFTY:RSIDivergence
ACTIVE_STRATEGY_ALLOWLIST = {
    tuple(item.strip().split(":", 1))
    for item in os.getenv(
        "ACTIVE_STRATEGY_ALLOWLIST",
        "BANKNIFTY:RSIDivergence,BANKNIFTY:VWAPReversion,BANKNIFTY:ORBBreakout,BANKNIFTY:MeanReversion",
    ).split(",")
    if ":" in item.strip()
}
SHADOW_SIGNAL_LOG = os.getenv("SHADOW_SIGNAL_LOG", "true").lower() in ("1", "true", "yes", "on")
SHADOW_LOG_FILE = os.getenv("SHADOW_LOG_FILE", f"{LOG_DIR}/shadow_signals.csv")
SIGNAL_CONSENSUS_ENABLED = os.getenv("SIGNAL_CONSENSUS_ENABLED", "true").lower() in ("1", "true", "yes", "on")
MIN_SIGNAL_CONSENSUS = max(1, int(os.getenv("MIN_SIGNAL_CONSENSUS", "2")))
FALLBACK_VIX = float(os.getenv("FALLBACK_VIX", "15.0"))
