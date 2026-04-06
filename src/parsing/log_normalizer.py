"""Log message normalization."""

import re
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class LogNormalizer:
    """Normalize and clean log messages."""
    
    @staticmethod
    def normalize(log: Dict) -> Dict:
        """Normalize a single log entry."""
        normalized = log.copy()
        
        # Clean message
        if 'message' in normalized:
            normalized['message'] = LogNormalizer._clean_message(normalized['message'])
        
        # Standardize level
        if 'level' in normalized:
            normalized['level'] = normalized['level'].upper()
        
        return normalized
    
    @staticmethod
    def _clean_message(message: str) -> str:
        """Clean a log message."""
        # Remove extra whitespace
        message = re.sub(r'\s+', ' ', message).strip()
        
        # Remove special characters (optional)
        # message = re.sub(r'[^a-zA-Z0-9\s\-_/=:\\.]', '', message)
        
        return message
    
    @staticmethod
    def normalize_batch(logs: List[Dict]) -> List[Dict]:
        """Normalize a batch of logs."""
        return [LogNormalizer.normalize(log) for log in logs]
