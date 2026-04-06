"""Main package module."""

__version__ = "1.0.0"
__author__ = "Your Name"

from config.logging_config import LOGGING_CONFIG
import logging.config

logging.config.dictConfig(LOGGING_CONFIG)
