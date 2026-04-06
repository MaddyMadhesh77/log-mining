"""Spark batch processing."""

import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class SparkBatch:
    """Spark Core based batch processing."""
    
    def __init__(self, spark_session):
        """Initialize batch processor."""
        self.spark = spark_session
    
    def process_logs(self, logs: List[Dict]):
        """Process logs using Spark."""
        try:
            df = self.spark.createDataFrame(logs)
            
            # Example transformations
            df = df.filter(df.level.isin(['ERROR', 'CRITICAL']))
            df = df.groupBy('source').count()
            
            results = df.collect()
            logger.info(f"Processed batch with {len(results)} groups")
            
            return results
        except Exception as e:
            logger.error(f"Error processing batch: {e}")
            return []
