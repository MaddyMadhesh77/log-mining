"""Unified storage manager."""

import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class StorageManager:
    """Unified storage manager supporting multiple backends."""
    
    def __init__(self):
        """Initialize storage manager."""
        self.backends = {}
    
    def register_backend(self, name: str, backend):
        """Register a storage backend."""
        self.backends[name] = backend
        logger.info(f"Registered storage backend: {name}")
    
    def save(self, data: List[Dict], backend: str = 'default', **kwargs):
        """Save data to configured backend."""
        if backend not in self.backends:
            logger.error(f"Backend not found: {backend}")
            return False
        
        try:
            self.backends[backend].save(data, **kwargs)
            logger.info(f"Saved data to {backend}")
            return True
        except Exception as e:
            logger.error(f"Failed to save data: {e}")
            return False
    
    def load(self, backend: str = 'default', **kwargs) -> List[Dict]:
        """Load data from configured backend."""
        if backend not in self.backends:
            logger.error(f"Backend not found: {backend}")
            return []
        
        try:
            data = self.backends[backend].load(**kwargs)
            logger.info(f"Loaded data from {backend}")
            return data
        except Exception as e:
            logger.error(f"Failed to load data: {e}")
            return []
