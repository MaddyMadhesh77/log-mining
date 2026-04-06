"""Tests for storage modules."""

import unittest
from src.storage.storage_manager import StorageManager


class TestStorage(unittest.TestCase):
    """Test storage module."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.manager = StorageManager()
    
    def test_backend_registration(self):
        """Test backend registration."""
        class MockBackend:
            def save(self, data):
                pass
        
        backend = MockBackend()
        self.manager.register_backend('mock', backend)
        
        self.assertIn('mock', self.manager.backends)


if __name__ == '__main__':
    unittest.main()
