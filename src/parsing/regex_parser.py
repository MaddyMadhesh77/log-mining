"""Regex-based log parsing."""

import re
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class RegexParser:
    """Parse logs using regular expressions."""
    
    def __init__(self):
        """Initialize regex parser."""
        self.patterns = self._build_patterns()
    
    @staticmethod
    def _build_patterns() -> Dict[str, re.Pattern]:
        """Build regex patterns for common log formats."""
        return {
            'syslog': re.compile(
                r'(?P<timestamp>\w+\s+\d+\s+[\d:]+)\s+(?P<host>\S+)\s+(?P<process>\S+):?\s+(?P<message>.*)'
            ),
            'apache': re.compile(
                r'(?P<host>\S+)\s+(?P<ident>\S+)\s+(?P<user>\S+)\s+\[(?P<timestamp>[^\]]+)\]\s+"(?P<request>[^"]+)"\s+(?P<status>\d+)\s+(?P<size>\d+)'
            ),
            'json': re.compile(r'^{.*}$'),
        }
    
    def parse(self, log_message: str) -> Dict:
        """Parse a log message."""
        for pattern_name, pattern in self.patterns.items():
            match = pattern.match(log_message)
            if match:
                return {
                    'pattern': pattern_name,
                    'data': match.groupdict()
                }
        
        return {'pattern': 'unknown', 'data': {'message': log_message}}
