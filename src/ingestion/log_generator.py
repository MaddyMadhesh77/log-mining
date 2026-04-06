"""Synthetic log generator for testing and development."""

import random
import time
from datetime import datetime, timedelta
from typing import List, Dict


class LogGenerator:
    """Generate synthetic logs for testing pattern mining algorithms."""
    
    LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    SOURCES = ['kernel', 'systemd', 'apache', 'nginx', 'database', 'app_server']
    
    SAMPLE_MESSAGES = [
        'Starting service',
        'Connection established',
        'Processing request',
        'Cache hit',
        'Query executed',
        'User authenticated',
        'File uploaded',
        'Scheduled task started',
        'Memory usage normal',
        'CPU load increasing',
    ]
    
    def __init__(self, seed=None):
        """Initialize log generator."""
        if seed:
            random.seed(seed)
    
    def generate_log(self, timestamp: datetime = None) -> Dict:
        """Generate a single log entry."""
        if timestamp is None:
            timestamp = datetime.now()
        
        return {
            'timestamp': timestamp.isoformat(),
            'level': random.choice(self.LOG_LEVELS),
            'source': random.choice(self.SOURCES),
            'message': random.choice(self.SAMPLE_MESSAGES),
            'pid': random.randint(100, 99999),
            'user': f'user_{random.randint(1, 100)}',
        }
    
    def generate_batch(self, count: int, start_time: datetime = None) -> List[Dict]:
        """Generate a batch of log entries."""
        if start_time is None:
            start_time = datetime.now()
        
        logs = []
        for i in range(count):
            timestamp = start_time + timedelta(seconds=i)
            logs.append(self.generate_log(timestamp))
        
        return logs
