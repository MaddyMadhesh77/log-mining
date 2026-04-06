"""Feature extraction from logs."""

import logging
from typing import List, Dict, Tuple
import numpy as np

logger = logging.getLogger(__name__)


class FeatureExtractor:
    """Extract features from logs for ML models."""
    
    @staticmethod
    def extract_features(log: Dict) -> Dict:
        """Extract features from a single log."""
        features = {
            'message_length': len(log.get('message', '')),
            'token_count': len(log.get('tokens', [])),
            'level_severity': FeatureExtractor._level_to_severity(log.get('level', 'INFO')),
        }
        
        return features
    
    @staticmethod
    def _level_to_severity(level: str) -> int:
        """Convert log level to severity score."""
        severity_map = {
            'DEBUG': 1,
            'INFO': 2,
            'WARNING': 3,
            'ERROR': 4,
            'CRITICAL': 5,
        }
        return severity_map.get(level.upper(), 2)
    
    @staticmethod
    def extract_features_batch(logs: List[Dict]) -> List[Dict]:
        """Extract features from multiple logs."""
        return [FeatureExtractor.extract_features(log) for log in logs]
