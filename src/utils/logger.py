"""Project-wide logging setup."""

import logging
import logging.config
from config.logging_config import LOGGING_CONFIG


def setup_logging():
    """Configure logging for the project."""
    logging.config.dictConfig(LOGGING_CONFIG)
    logger = logging.getLogger(__name__)
    logger.info("Logging configured")
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a specific module."""
    return logging.getLogger(name)
