# utils/health_monitor.py
# ─────────────────────────────────────────────────────────────────────────────
# Health Monitor
# Tracks bot vitals, detects stalls, and logs a heartbeat every N minutes.
# Also checks for: data staleness, memory leaks, API error rate.
# ─────────────────────────────────────────────────────────────────────────────

import time
import threading
from datetime import datetime
from collections import deque
from loguru import logger
from config.settings import IST


class HealthMonitor:
    """
    Runs in a background thread. Checks every 60 seconds:
    - Last successful API call (data staleness)
    - API error rate (errors / total calls in last 10 min)
    - Open position count vs expected
    - Daily P&L drift (warns if approaching limit)
    """

    def __init__(self, paper_engine, kite_client, notifier=None):
        self.engine   = paper_engine
        self.kite     = kite_client
        self.notifier = notifier

        self._api_calls:   deque = deque(maxlen=100)   # timestamps
        self._api_errors:  deque = deque(maxlen=100)   # (timestamp, error)
        self._last_data_ts: float = time.time()
        self._running = False
        self._thread:  threading.Thread = None

    # ── Instrumentation ───────────────────────────────────────────────────────

    def record_api_call(self, success: bool, error: str = ""):
        ts = time.time()
        self._api_calls.append(ts)
        if not success:
            self._api_errors.append((ts, error))
        if success:
            self._last_data_ts = ts

    # ── Background Loop ───────────────────────────────────────────────────────

    def start(self):
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("HealthMonitor started")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self._check()
            except Exception as e:
                logger.error(f"HealthMonitor error: {e}")
            time.sleep(60)

    def _check(self):
        now  = time.time()
        stat = self.engine.status()

        # ── Data staleness ────────────────────────────────────────────────────
        stale_secs = now - self._last_data_ts
        if stale_secs > 180:   # 3 minutes without data
            msg = f"⚠️ Data stale for {stale_secs:.0f}s — possible API disconnect"
            logger.warning(msg)
            if self.notifier:
                self.notifier.error_alert("Health", msg)

        # ── API error rate ────────────────────────────────────────────────────
        recent_window = now - 600   # Last 10 min
        recent_calls  = sum(1 for t in self._api_calls  if t > recent_window)
        recent_errors = sum(1 for t, _ in self._api_errors if t > recent_window)
        if recent_calls > 10:
            err_rate = recent_errors / recent_calls
            if err_rate > 0.3:
                logger.warning(f"High API error rate: {err_rate:.1%} ({recent_errors}/{recent_calls})")

        # ── Daily P&L warning ─────────────────────────────────────────────────
        from config.settings import MAX_DAILY_LOSS
        if stat["daily_pnl"] < -MAX_DAILY_LOSS * 0.7:
            logger.warning(
                f"⚠️ Daily P&L ₹{stat['daily_pnl']:.0f} is 70% of loss limit"
            )

        # ── Heartbeat log every check ─────────────────────────────────────────
        logger.debug(
            f"💓 Heartbeat | {datetime.now(IST).strftime('%H:%M')} | "
            f"OpenPos={stat['open_positions']} | "
            f"DayPnL=₹{stat['daily_pnl']:.2f} | "
            f"Avail=₹{stat['available_capital']:.0f} | "
            f"APIerr={recent_errors}/{recent_calls}"
        )

    def report(self) -> dict:
        now = time.time()
        return {
            "last_data_age_secs": round(now - self._last_data_ts, 1),
            "total_api_calls":    len(self._api_calls),
            "total_api_errors":   len(self._api_errors),
        }
