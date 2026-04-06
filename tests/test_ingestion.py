"""Tests for data ingestion modules."""

import unittest
from src.ingestion.log_generator import LogGenerator


class TestIngestion(unittest.TestCase):
    """Test ingestion module."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.generator = LogGenerator(seed=42)
    
    def test_log_generation(self):
        """Test log generation."""
        log = self.generator.generate_log()
        
        self.assertIn('timestamp', log)
        self.assertIn('message', log)
        self.assertIn('level', log)
    
    def test_batch_generation(self):
        """Test batch log generation."""
        batch = self.generator.generate_batch(10)
        
        self.assertEqual(len(batch), 10)
        self.assertIsInstance(batch, list)


if __name__ == '__main__':
    unittest.main()
