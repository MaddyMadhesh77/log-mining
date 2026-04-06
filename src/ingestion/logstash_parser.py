"""Logstash/Fluentd integration for log ingestion."""

import logging

logger = logging.getLogger(__name__)


class LogstashParser:
    """Parse logs from Logstash/Fluentd format."""
    
    @staticmethod
    def parse_logstash_entry(entry: dict) -> dict:
        """Convert Logstash format to internal format."""
        return {
            'timestamp': entry.get('@timestamp'),
            'level': entry.get('level', 'INFO'),
            'source': entry.get('type', 'unknown'),
            'message': entry.get('message', ''),
            'host': entry.get('host', ''),
        }
