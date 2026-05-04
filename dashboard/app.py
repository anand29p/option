# dashboard/app.py
# ─────────────────────────────────────────────────────────────────────────────
# Web Dashboard — Flask server serving real-time bot state
#
# Access at: http://127.0.0.1:5000
# Auto-refreshes every 5 seconds via JavaScript polling.
# ─────────────────────────────────────────────────────────────────────────────

import csv
import json
from pathlib import Path
from datetime import datetime

from flask import Flask, jsonify, render_template
from tinydb import TinyDB

from config.settings import LOG_DIR, TRADE_LOG, IST, PAPER_CAPITAL

app = Flask(__name__)
_bot = None   # Injected at startup


def start_dashboard(bot=None, host="127.0.0.1", port=5000):
    """Start Flask server. Pass the AlgoBot instance to serve live state."""
    global _bot
    _bot = bot
    app.run(host=host, port=port, debug=False, use_reloader=False)


# ── API endpoints ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    """Bot + engine status snapshot."""
    if _bot is None:
        return jsonify({
            "mode": "dashboard-only",
            "capital": PAPER_CAPITAL,
            "available_capital": PAPER_CAPITAL,
            "open_positions": 0,
            "daily_pnl": 0.0,
            "total_trades": 0,
            "time": datetime.now(IST).strftime("%H:%M:%S IST"),
            "date": datetime.now(IST).strftime("%a %d %b %Y"),
        })

    s = _bot.engine.status()
    s["mode"] = "PAPER"
    s["time"] = datetime.now(IST).strftime("%H:%M:%S IST")
    s["date"] = datetime.now(IST).strftime("%a %d %b %Y")
    return jsonify(s)


@app.route("/api/positions")
def api_positions():
    """Open positions with live unrealized P&L."""
    if _bot is None:
        return jsonify([])
    return jsonify(_bot.engine.open_positions_summary())


@app.route("/api/trades")
def api_trades():
    """Closed trades from TinyDB (all sessions)."""
    db_path = Path(LOG_DIR) / "paper_trades.json"
    if not db_path.exists():
        return jsonify([])
    db = TinyDB(str(db_path))
    trades = sorted(db.all(), key=lambda x: x.get("date", ""), reverse=True)
    return jsonify(trades[:100])   # Last 100 trades


@app.route("/api/global")
def api_global():
    """Global market context (GIFT Nifty, Dow, etc.)."""
    try:
        from utils.global_context import get_global_context
        ctx = get_global_context()
        return jsonify(ctx.to_dict())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/sentiment")
def api_sentiment():
    """News sentiment from Indian financial RSS feeds."""
    try:
        from utils.news_sentiment import get_news_sentiment
        s = get_news_sentiment()
        return jsonify(s.to_dict())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/pnl_curve")
def api_pnl_curve():
    """Daily P&L curve from trade CSV for Chart.js."""
    csv_path = Path(TRADE_LOG)
    if not csv_path.exists():
        return jsonify({"labels": [], "data": []})

    daily = {}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            d   = row.get("date", "")
            pnl = float(row.get("net_pnl", 0) or 0)
            daily[d] = daily.get(d, 0) + pnl

    labels = sorted(daily.keys())
    data   = [round(daily[l], 2) for l in labels]
    return jsonify({"labels": labels, "data": data})
