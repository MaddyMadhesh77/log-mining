"""Encoding of categorical features."""

import logging
from typing import Dict, List, Tuple
import numpy as np

logger = logging.getLogger(__name__)


class Encoder:
    """Encode categorical and numerical features."""
    
    def __init__(self):
        """Initialize encoder."""
        self.level_map = {'DEBUG': 0, 'INFO': 1, 'WARNING': 2, 'ERROR': 3, 'CRITICAL': 4}
        self.source_map = {}
        self.source_counter = 0
    
    def encode_level(self, level: str) -> int:
        """Encode log level."""
        return self.level_map.get(level.upper(), 1)
    
    def encode_source(self, source: str) -> int:
        """Encode log source with automatic mapping."""
        if source not in self.source_map:
            self.source_map[source] = self.source_counter
            self.source_counter += 1
        return self.source_map[source]
    
    def encode_log(self, log: Dict) -> Dict:
        """Encode a single log entry."""
        encoded = log.copy()
        
        if 'level' in encoded:
            encoded['level_encoded'] = self.encode_level(encoded['level'])
        
        if 'source' in encoded:
            encoded['source_encoded'] = self.encode_source(encoded['source'])
        
        return encoded
    
    def encode_batch(self, logs: List[Dict]) -> List[Dict]:
        """Encode multiple logs."""
        return [self.encode_log(log) for log in logs]
