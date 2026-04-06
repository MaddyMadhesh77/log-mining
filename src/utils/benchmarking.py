"""Benchmarking utilities."""

import logging
import time
from typing import List, Dict, Callable

logger = logging.getLogger(__name__)


class Benchmarker:
    """Benchmark and profile code performance."""
    
    def __init__(self):
        """Initialize benchmarker."""
        self.results = []
    
    def benchmark(self, func: Callable, *args, repetitions: int = 1, **kwargs) -> Dict:
        """
        Benchmark a function.
        
        Args:
            func: Function to benchmark
            repetitions: Number of times to run
            args: Function arguments
            kwargs: Function keyword arguments
        
        Returns:
            Benchmark results
        """
        times = []
        
        for _ in range(repetitions):
            start = time.time()
            func(*args, **kwargs)
            end = time.time()
            times.append(end - start)
        
        result = {
            'function': func.__name__,
            'repetitions': repetitions,
            'times': times,
            'min': min(times),
            'max': max(times),
            'avg': sum(times) / len(times),
        }
        
        self.results.append(result)
        logger.info(f"Benchmark: {func.__name__} avg={result['avg']:.4f}s")
        
        return result
    
    def report(self) -> str:
        """Generate benchmark report."""
        lines = ['Benchmark Report', '=' * 50]
        
        for result in self.results:
            lines.append(f"Function: {result['function']}")
            lines.append(f"  Repetitions: {result['repetitions']}")
            lines.append(f"  Min: {result['min']:.4f}s")
            lines.append(f"  Max: {result['max']:.4f}s")
            lines.append(f"  Avg: {result['avg']:.4f}s")
            lines.append('')
        
        return '\n'.join(lines)
