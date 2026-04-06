"""Kafka producer for sending logs to Kafka topic."""

import json
from typing import Dict
import logging

logger = logging.getLogger(__name__)


class KafkaProducer:
    """Send log messages to Kafka broker."""
    
    def __init__(self, bootstrap_servers: list = None, topic: str = None):
        """Initialize Kafka producer."""
        self.bootstrap_servers = bootstrap_servers or ['localhost:9092']
        self.topic = topic or 'system_logs'
        self.producer = None
    
    def connect(self):
        """Connect to Kafka broker."""
        try:
            from confluent_kafka import Producer
            self.producer = Producer({
                'bootstrap.servers': ','.join(self.bootstrap_servers)
            })
            logger.info(f"Connected to Kafka: {self.bootstrap_servers}")
        except Exception as e:
            logger.error(f"Failed to connect to Kafka: {e}")
            raise
    
    def send_log(self, log_entry: Dict):
        """Send a single log entry to Kafka."""
        if self.producer is None:
            self.connect()
        
        try:
            message = json.dumps(log_entry)
            self.producer.produce(self.topic, message.encode('utf-8'))
            self.producer.flush(timeout=1)
            logger.debug(f"Sent log to {self.topic}")
        except Exception as e:
            logger.error(f"Failed to send log: {e}")
    
    def send_batch(self, log_entries: list):
        """Send multiple log entries to Kafka."""
        for log_entry in log_entries:
            self.send_log(log_entry)
    
    def close(self):
        """Close Kafka connection."""
        if self.producer:
            self.producer.flush()
