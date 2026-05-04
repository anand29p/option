# utils/notifier.py
# ─────────────────────────────────────────────────────────────────────────────
# Notification System
# Sends alerts via Telegram (optional) and always logs to console.
# Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env to enable.
# If not configured, falls back to console-only (no crash).
# ─────────────────────────────────────────────────────────────────────────────

import os
import requests
from datetime import datetime
from loguru import logger
from config.settings import IST

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)


def _send_telegram(message: str):
    """Send a Telegram message. Silently skips if not configured."""
    if not TELEGRAM_ENABLED:
        return
    try:
        url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       message,
            "parse_mode": "HTML",
        }, timeout=5)
        if not resp.ok:
            logger.warning(f"Telegram send failed: {resp.status_code}")
    except Exception as e:
        logger.warning(f"Telegram error (non-fatal): {e}")


class Notifier:
    """
    Central notification hub. Call these methods from PaperEngine / Bot.
    All messages also go to loguru (console + file).
    """

    @staticmethod
    def trade_entry(trade_id: str, symbol: str, strategy: str,
                    entry_price: float, sl: float, target: float, qty: int):
        msg = (
            f"✅ <b>ENTRY</b> [{trade_id}]\n"
            f"📌 {symbol}\n"
            f"🧠 Strategy: {strategy}\n"
            f"💰 Entry: ₹{entry_price:.1f} | Qty: {qty}\n"
            f"🛑 SL: ₹{sl:.1f} | 🎯 Target: ₹{target:.1f}\n"
            f"🕐 {datetime.now(IST).strftime('%H:%M:%S IST')}"
        )
        logger.info(f"ENTRY [{trade_id}] {symbol} @ ₹{entry_price}")
        _send_telegram(msg)

    @staticmethod
    def trade_exit(trade_id: str, symbol: str, entry: float,
                   exit_price: float, net_pnl: float, reason: str):
        icon = "🟢" if net_pnl >= 0 else "🔴"
        msg = (
            f"{icon} <b>EXIT</b> [{trade_id}]\n"
            f"📌 {symbol}\n"
            f"📈 Entry: ₹{entry:.1f} → Exit: ₹{exit_price:.1f}\n"
            f"💵 Net P&L: ₹{net_pnl:+.2f}\n"
            f"📋 Reason: {reason}\n"
            f"🕐 {datetime.now(IST).strftime('%H:%M:%S IST')}"
        )
        logger.info(f"EXIT [{trade_id}] {symbol} Net=₹{net_pnl:+.2f} ({reason})")
        _send_telegram(msg)

    @staticmethod
    def daily_loss_limit(daily_pnl: float):
        msg = (
            f"⛔ <b>DAILY LOSS LIMIT HIT</b>\n"
            f"P&L: ₹{daily_pnl:+.2f}\n"
            f"Bot stopped trading for today.\n"
            f"🕐 {datetime.now(IST).strftime('%H:%M:%S IST')}"
        )
        logger.warning(f"Daily loss limit hit: ₹{daily_pnl:.2f}")
        _send_telegram(msg)

    @staticmethod
    def daily_summary(date: str, trades: int, net_pnl: float,
                      win_rate: float, charges: float):
        icon = "📈" if net_pnl >= 0 else "📉"
        msg = (
            f"{icon} <b>Daily Summary — {date}</b>\n"
            f"Trades: {trades} | Win Rate: {win_rate:.1f}%\n"
            f"Net P&L: ₹{net_pnl:+.2f}\n"
            f"Charges paid: ₹{charges:.2f}"
        )
        logger.info(f"Daily summary: {trades} trades, Net=₹{net_pnl:+.2f}")
        _send_telegram(msg)

    @staticmethod
    def error_alert(context: str, error: str):
        msg = f"⚠️ <b>ERROR</b>\n{context}\n<code>{error[:200]}</code>"
        logger.error(f"Alert: {context} — {error}")
        _send_telegram(msg)

    @staticmethod
    def bot_started(mode: str, capital: float):
        msg = (
            f"🚀 <b>Bot Started</b>\n"
            f"Mode: {mode.upper()}\n"
            f"Capital: ₹{capital:,.0f}\n"
            f"🕐 {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}"
        )
        logger.info(f"Bot started | mode={mode} capital=₹{capital:,.0f}")
        _send_telegram(msg)

    @staticmethod
    def eod_squareoff(count: int):
        msg = f"🔔 <b>EOD Square-off</b> — {count} position(s) closed"
        logger.info(f"EOD squareoff: {count} positions closed")
        _send_telegram(msg)
