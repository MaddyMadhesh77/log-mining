"""NoSQL database handlers (MongoDB, Cassandra)."""

import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class NoSQLHandler:
    """Handle NoSQL database operations."""
    
    def __init__(self, db_type: str = 'mongodb', host: str = 'localhost'):
        """Initialize NoSQL handler."""
        self.db_type = db_type
        self.host = host
        self.client = None
        self.db = None
    
    def connect(self):
        """Connect to NoSQL database."""
        try:
            if self.db_type == 'mongodb':
                from pymongo import MongoClient
                self.client = MongoClient(self.host)
                self.db = self.client['logs_db']
                logger.info(f"Connected to MongoDB: {self.host}")
        except Exception as e:
            logger.error(f"Failed to connect to {self.db_type}: {e}")
    
    def insert_logs(self, logs: List[Dict], collection: str = 'logs'):
        """Insert logs into database."""
        if self.db is None:
            self.connect()
        
        try:
            self.db[collection].insert_many(logs)
            logger.info(f"Inserted {len(logs)} logs into {collection}")
        except Exception as e:
            logger.error(f"Failed to insert logs: {e}")
