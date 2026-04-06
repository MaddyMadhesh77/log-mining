"""Input validation utilities."""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class Validators:
    """Validate input data."""
    
    @staticmethod
    def validate_log(log: Dict) -> bool:
        """Validate a single log entry."""
        required_fields = ['timestamp', 'message']
        
        for field in required_fields:
            if field not in log:
                logger.warning(f"Missing required field: {field}")
                return False
        
        return True
    
    @staticmethod
    def validate_logs(logs: List[Dict]) -> bool:
        """Validate a batch of logs."""
        if not logs:
            logger.warning("Empty log batch")
            return False
        
        for i, log in enumerate(logs):
            if not Validators.validate_log(log):
                logger.warning(f"Invalid log at index {i}")
                return False
        
        return True
