import csv
from datetime import datetime
from pathlib import Path

from config.settings import IST, LOG_DIR, SHADOW_LOG_FILE


class ShadowSignalJournal:
    """CSV journal for strategy signals that are observed but not executed."""

    def __init__(self, path: str = SHADOW_LOG_FILE):
        self.path = Path(path)
        Path(LOG_DIR).mkdir(exist_ok=True)
        self._init_file()

    def _init_file(self):
        if self.path.exists():
            return
        with open(self.path, "w", newline="") as f:
            csv.writer(f).writerow([
                "date",
                "time",
                "index",
                "strategy",
                "signal",
                "spot_price",
                "session",
                "regime",
                "trend",
                "vix",
                "action",
                "reason",
            ])

    def record(
        self,
        *,
        index: str,
        strategy: str,
        signal: str,
        spot_price: float,
        session: str,
        regime: str,
        trend: str,
        vix: float,
        action: str,
        reason: str,
    ):
        now = datetime.now(IST)
        with open(self.path, "a", newline="") as f:
            csv.writer(f).writerow([
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M:%S"),
                index,
                strategy,
                signal,
                round(float(spot_price), 2),
                session,
                regime,
                trend,
                round(float(vix), 2),
                action,
                reason,
            ])
