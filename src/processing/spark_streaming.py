"""Spark Structured Streaming."""

import logging

logger = logging.getLogger(__name__)


class SparkStreaming:
    """Spark Structured Streaming for continuous processing."""
    
    def __init__(self, spark_session):
        """Initialize streaming processor."""
        self.spark = spark_session
    
    def start_stream(self, source_path: str, checkpoint_path: str):
        """Start streaming from a source."""
        try:
            df = self.spark.readStream \
                .schema("message STRING, timestamp TIMESTAMP") \
                .json(source_path)
            
            query = df.writeStream \
                .mode("append") \
                .format("console") \
                .option("checkpointLocation", checkpoint_path) \
                .start()
            
            logger.info("Streaming query started")
            return query
        except Exception as e:
            logger.error(f"Error starting stream: {e}")
            return None
