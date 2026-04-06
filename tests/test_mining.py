"""Tests for pattern mining modules."""

import unittest
from src.mining.frequent_pattern import FrequentPatternMining


class TestMining(unittest.TestCase):
    """Test mining module."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.miner = FrequentPatternMining(min_support=0.1)
    
    def test_frequent_pattern_mining(self):
        """Test frequent pattern extraction."""
        transactions = [
            {'error', 'timeout'},
            {'error', 'connection'},
            {'error', 'timeout'},
            {'timeout', 'retry'},
        ]
        
        patterns = self.miner.find_patterns(transactions)
        self.assertIsInstance(patterns, dict)


if __name__ == '__main__':
    unittest.main()
