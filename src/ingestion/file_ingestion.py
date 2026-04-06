"""File-based batch log ingestion."""

import os
import json
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class FileIngestion:
    """Ingest logs from files."""
    
    @staticmethod
    def read_logs_from_file(filepath: str) -> List[Dict]:
        """Read logs from a JSON or text file."""
        logs = []
        
        if not os.path.exists(filepath):
            logger.error(f"File not found: {filepath}")
            return logs
        
        try:
            if filepath.endswith('.json'):
                with open(filepath, 'r') as f:
                    logs = json.load(f)
            else:
                with open(filepath, 'r') as f:
                    for line in f:
                        try:
                            log = json.loads(line)
                            logs.append(log)
                        except json.JSONDecodeError:
                            logger.warning(f"Could not parse line: {line}")
            
            logger.info(f"Read {len(logs)} logs from {filepath}")
        except Exception as e:
            logger.error(f"Error reading file {filepath}: {e}")
        
        return logs
    
    @staticmethod
    def write_logs_to_file(logs: List[Dict], filepath: str):
        """Write logs to a JSON file."""
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w') as f:
                json.dump(logs, f, indent=2)
            logger.info(f"Wrote {len(logs)} logs to {filepath}")
        except Exception as e:
            logger.error(f"Error writing to file {filepath}: {e}")
