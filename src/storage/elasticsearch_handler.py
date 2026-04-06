"""Elasticsearch indexing and search."""

import logging
import json
from typing import List, Dict

logger = logging.getLogger(__name__)


class ElasticsearchHandler:
    """Handle Elasticsearch indexing and search."""
    
    def __init__(self, hosts: list = None, index: str = 'logs'):
        """Initialize Elasticsearch handler."""
        self.hosts = hosts or ['localhost:9200']
        self.index = index
        self.es = None
    
    def connect(self):
        """Connect to Elasticsearch."""
        try:
            from elasticsearch import Elasticsearch
            self.es = Elasticsearch(self.hosts)
            logger.info(f"Connected to Elasticsearch: {self.hosts}")
        except Exception as e:
            logger.error(f"Failed to connect to Elasticsearch: {e}")
    
    def index_logs(self, logs: List[Dict]):
        """Index logs in Elasticsearch."""
        if self.es is None:
            self.connect()
        
        try:
            for i, log in enumerate(logs):
                self.es.index(index=self.index, id=i, body=log)
            
            logger.info(f"Indexed {len(logs)} logs")
        except Exception as e:
            logger.error(f"Failed to index logs: {e}")
    
    def search(self, query: Dict) -> List[Dict]:
        """Search logs in Elasticsearch."""
        if self.es is None:
            self.connect()
        
        try:
            results = self.es.search(index=self.index, body=query)
            return results.get('hits', {}).get('hits', [])
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
