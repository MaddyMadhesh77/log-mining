"""Log data cleaning and preprocessing."""

import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class LogCleaner:
    """Clean and prepare logs for processing."""
    
    @staticmethod
    def remove_duplicates(logs: List[Dict]) -> List[Dict]:
        """Remove duplicate log entries."""
        seen = set()
        cleaned = []
        
        for log in logs:
            # Create a hashable representation
            log_tuple = tuple(sorted(log.items()))
            if log_tuple not in seen:
                seen.add(log_tuple)
                cleaned.append(log)
        
        logger.info(f"Removed {len(logs) - len(cleaned)} duplicates")
        return cleaned
    
    @staticmethod
    def remove_noise(logs: List[Dict]) -> List[Dict]:
        """Remove noisy/malformed entries."""
        cleaned = []
        
        for log in logs:
            if log.get('message') and log.get('timestamp'):
                cleaned.append(log)
        
        logger.info(f"Removed {len(logs) - len(cleaned)} noisy entries")
        return cleaned
    
    @staticmethod
    def clean_batch(logs: List[Dict]) -> List[Dict]:
        """Apply all cleaning operations."""
        logs = LogCleaner.remove_noise(logs)
        logs = LogCleaner.remove_duplicates(logs)
        return logs
