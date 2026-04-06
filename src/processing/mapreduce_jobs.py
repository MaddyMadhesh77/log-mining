"""MapReduce-style operations."""

import logging
from typing import List, Dict, Callable

logger = logging.getLogger(__name__)


class MapReduceJobs:
    """MapReduce operations on log data."""
    
    @staticmethod
    def map_operation(logs: List[Dict], map_func: Callable) -> List:
        """Apply map function to logs."""
        return [map_func(log) for log in logs]
    
    @staticmethod
    def reduce_operation(mapped_data: List, reduce_func: Callable, initial=None):
        """Apply reduce function."""
        result = initial
        for item in mapped_data:
            result = reduce_func(result, item)
        return result
    
    @staticmethod
    def count_by_level(logs: List[Dict]) -> Dict[str, int]:
        """Count logs by level (MapReduce example)."""
        # Map
        mapped = MapReduceJobs.map_operation(
            logs,
            lambda log: (log.get('level', 'UNKNOWN'), 1)
        )
        
        # Reduce
        result = {}
        for level, count in mapped:
            result[level] = result.get(level, 0) + count
        
        return result
