# config/logging_config.py
# ─────────────────────────────────────────────────────────────────────────────
# Centralized Loguru logging configuration.
# Import and call setup_logging() once at startup (done in main.py).
# ─────────────────────────────────────────────────────────────────────────────

import sys
from pathlib import Path
from loguru import logger
from config.settings import LOG_DIR, LOG_LEVEL


def setup_logging(log_dir: str = LOG_DIR, level: str = LOG_LEVEL):
    """
    Configure loguru sinks:
    1. Colored stdout (INFO and above)
    2. Rotating daily file (DEBUG and above, 14-day retention)
    3. Separate error-only file
    """
    Path(log_dir).mkdir(exist_ok=True)

    logger.remove()  # Remove default handler

    # ── Console ──────────────────────────────────────────────────────────────
    logger.add(
        sys.stdout,
        level="INFO",
        colorize=True,
        format=(
            "<green>{time:HH:mm:ss}</green> "
            "| <level>{level: <8}</level> "
            "| <cyan>{name}</cyan>:<cyan>{line}</cyan> "
            "| {message}"
        ),
    )

    # ── Daily rotating log file ───────────────────────────────────────────────
    logger.add(
        f"{log_dir}/bot_{{time:YYYY-MM-DD}}.log",
        level="DEBUG",
        rotation="00:00",       # New file each day at midnight
        retention="14 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{line} | {message}",
        enqueue=False,          # Avoid multiprocessing pipes in restricted shells
    )

    # ── Error-only log ────────────────────────────────────────────────────────
    logger.add(
        f"{log_dir}/errors.log",
        level="ERROR",
        rotation="1 week",
        retention="4 weeks",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{line} | {message}\n{exception}",
        backtrace=True,
        diagnose=True,
    )

    logger.info(f"Logging initialized → {log_dir}/ (level={level})")
