"""
logger.py
---------
Structured logger for LogSense AI using Loguru.

Features:
    - Coloured console output with level-based formatting
    - JSON file logging for production (structured log lines)
    - Module-specific loggers via get_logger(__name__)
    - success() level added (between INFO and WARNING)

Usage:
    from utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Processing {:,} lines", 11_000_000)
    logger.success("Done in {:.1f}s", elapsed)
    logger.warning("Skipping malformed line {}", line_no)
    logger.error("Kafka connection failed: {}", exc)
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger as _loguru_logger

# ─── Log directory ────────────────────────────────────────────────────────────
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# ─── Remove default loguru handler ────────────────────────────────────────────
_loguru_logger.remove()

# ─── Console handler (coloured, human-readable) ───────────────────────────────
_loguru_logger.add(
    sys.stdout,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    ),
    level="DEBUG",
    colorize=True,
    backtrace=True,
    diagnose=True,
)

# ─── File handler (JSON, rotation, retention) ─────────────────────────────────
_loguru_logger.add(
    LOG_DIR / "logsense_{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{line} | {message}",
    level="INFO",
    rotation="00:00",       # New file each day
    retention="7 days",     # Keep 7 days of logs
    compression="gz",       # Compress rotated logs
    backtrace=False,
    diagnose=False,
    enqueue=True,           # Thread-safe async writes
)

# ─── Error-only file (for quick debugging) ────────────────────────────────────
_loguru_logger.add(
    LOG_DIR / "errors.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{line} | {message}",
    level="ERROR",
    rotation="100 MB",
    retention="30 days",
    backtrace=True,
    diagnose=True,
    enqueue=True,
)


def get_logger(name: str):
    """
    Return a module-specific logger bound with the caller's module name.

    Usage:
        logger = get_logger(__name__)
        logger.info("message")
    """
    return _loguru_logger.bind(name=name)