"""Tests for log parsing modules."""

import unittest
from src.parsing.regex_parser import RegexParser
from src.parsing.log_normalizer import LogNormalizer


class TestParsing(unittest.TestCase):
    """Test parsing module."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.parser = RegexParser()
    
    def test_regex_parsing(self):
        """Test regex-based parsing."""
        message = "2024-01-01 10:00:00 ERROR Connection failed"
        result = self.parser.parse(message)
        
        self.assertIsNotNone(result)
        self.assertIn('pattern', result)
    
    def test_log_normalization(self):
        """Test log normalization."""
        log = {'message': 'Test   message', 'level': 'error'}
        normalized = LogNormalizer.normalize(log)
        
        self.assertEqual(normalized['message'], 'Test message')
        self.assertEqual(normalized['level'], 'ERROR')


if __name__ == '__main__':
    unittest.main()
