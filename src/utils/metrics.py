"""Performance metrics calculation."""

import logging
import time
from typing import Dict

logger = logging.getLogger(__name__)


class Metrics:
    """Calculate and track performance metrics."""
    
    @staticmethod
    def calculate_precision_recall(tp: int, fp: int, fn: int) -> Dict[str, float]:
        """Calculate precision and recall."""
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        
        return {
            'precision': precision,
            'recall': recall,
            'f1_score': 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0,
        }
    
    @staticmethod
    def calculate_accuracy(correct: int, total: int) -> float:
        """Calculate accuracy."""
        return correct / total if total > 0 else 0


class Timer:
    """Context manager for timing operations."""
    
    def __init__(self, operation_name: str = ''):
        """Initialize timer."""
        self.operation_name = operation_name
        self.start_time = None
        self.end_time = None
    
    def __enter__(self):
        """Start timer."""
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop timer and log duration."""
        self.end_time = time.time()
        duration = self.end_time - self.start_time
        
        if self.operation_name:
            logger.info(f"{self.operation_name} took {duration:.2f} seconds")
        
        return False
    
    def elapsed(self) -> float:
        """Get elapsed time."""
        if self.end_time is None:
            logger.warning("Timer not stopped yet")
            return 0
        
        return self.end_time - self.start_time
