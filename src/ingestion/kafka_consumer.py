"""Kafka consumer for reading logs from Kafka topic."""

import json
import logging
from typing import Generator, Dict

logger = logging.getLogger(__name__)


class KafkaConsumer:
    """Read log messages from Kafka broker."""
    
    def __init__(self, bootstrap_servers: list = None, topic: str = None, group_id: str = None):
        """Initialize Kafka consumer."""
        self.bootstrap_servers = bootstrap_servers or ['localhost:9092']
        self.topic = topic or 'system_logs'
        self.group_id = group_id or 'log_miners'
        self.consumer = None
    
    def connect(self):
        """Connect to Kafka broker."""
        try:
            from confluent_kafka import Consumer
            self.consumer = Consumer({
                'bootstrap.servers': ','.join(self.bootstrap_servers),
                'group.id': self.group_id,
                'auto.offset.reset': 'earliest',
            })
            self.consumer.subscribe([self.topic])
            logger.info(f"Connected to Kafka topic: {self.topic}")
        except Exception as e:
            logger.error(f"Failed to connect to Kafka: {e}")
            raise
    
    def consume(self, timeout: float = 1.0) -> Generator[Dict, None, None]:
        """Consume messages from Kafka."""
        if self.consumer is None:
            self.connect()
        
        try:
            while True:
                msg = self.consumer.poll(timeout=timeout)
                if msg is None:
                    continue
                
                if msg.error():
                    logger.error(f"Consumer error: {msg.error()}")
                    continue
                
                try:
                    log_entry = json.loads(msg.value().decode('utf-8'))
                    yield log_entry
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse message: {e}")
        except KeyboardInterrupt:
            logger.info("Consumer interrupted")
    
    def close(self):
        """Close Kafka connection."""
        if self.consumer:
            self.consumer.close()
