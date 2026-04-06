"""Tokenization of log messages."""

import re
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class Tokenizer:
    """Tokenize log messages into words."""
    
    @staticmethod
    def tokenize(message: str) -> List[str]:
        """Split message into tokens."""
        # Split on whitespace and common delimiters
        tokens = re.split(r'[\s\-,;:()]+', message)
        # Remove empty tokens
        return [t for t in tokens if t]
    
    @staticmethod
    def tokenize_logs(logs: List[Dict]) -> List[Dict]:
        """Add token field to each log."""
        for log in logs:
            if 'message' in log:
                log['tokens'] = Tokenizer.tokenize(log['message'])
        
        return logs
