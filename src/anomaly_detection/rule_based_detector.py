"""Rule-based anomaly detection."""

import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class RuleBasedDetector:
    """Rule-based anomaly detection."""
    
    def __init__(self):
        """Initialize rule-based detector."""
        self.rules = self._build_rules()
    
    @staticmethod
    def _build_rules() -> List[Dict]:
        """Build detection rules."""
        return [
            {'level': 'CRITICAL', 'action': 'flag'},
            {'level': 'ERROR', 'count_threshold': 10, 'action': 'flag'},
            {'source': 'unknown', 'action': 'investigate'},
        ]
    
    def detect(self, log: Dict) -> bool:
        """Check if log matches any anomaly rule."""
        for rule in self.rules:
            if self._matches_rule(log, rule):
                logger.debug(f"Log matched anomaly rule")
                return True
        
        return False
    
    @staticmethod
    def _matches_rule(log: Dict, rule: Dict) -> bool:
        """Check if a log matches a rule."""
        for key, value in rule.items():
            if key == 'action':
                continue
            if log.get(key) != value:
                return False
        return True
