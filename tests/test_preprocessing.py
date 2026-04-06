"""Tests for preprocessing modules."""

import unittest
from src.preprocessing.cleaner import LogCleaner
from src.preprocessing.tokenizer import Tokenizer


class TestPreprocessing(unittest.TestCase):
    """Test preprocessing module."""
    
    def test_remove_duplicates(self):
        """Test duplicate removal."""
        logs = [
            {'timestamp': '2024-01-01', 'message': 'Error occurred'},
            {'timestamp': '2024-01-01', 'message': 'Error occurred'},
            {'timestamp': '2024-01-02', 'message': 'Warning'},
        ]
        
        cleaned = LogCleaner.remove_duplicates(logs)
        self.assertEqual(len(cleaned), 2)
    
    def test_tokenization(self):
        """Test message tokenization."""
        message = "Connection error: timeout"
        tokens = Tokenizer.tokenize(message)
        
        self.assertGreater(len(tokens), 0)
        self.assertIn("Connection", tokens)


if __name__ == '__main__':
    unittest.main()
