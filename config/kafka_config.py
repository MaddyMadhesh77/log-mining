"""Kafka configuration module."""

from config.constants import KAFKA_BROKERS, KAFKA_TOPIC_LOGS, KAFKA_CONSUMER_GROUP

KAFKA_CONFIG = {
    'bootstrap.servers': ','.join(KAFKA_BROKERS),
    'group.id': KAFKA_CONSUMER_GROUP,
    'auto.offset.reset': 'earliest',
    'enable.auto.commit': True,
    'auto.commit.interval.ms': 1000,
}

KAFKA_PRODUCER_CONFIG = {
    'bootstrap.servers': ','.join(KAFKA_BROKERS),
}

KAFKA_CONSUMER_CONFIG = {
    'bootstrap.servers': ','.join(KAFKA_BROKERS),
    'group.id': KAFKA_CONSUMER_GROUP,
    'auto.offset.reset': 'earliest',
}

DEFAULT_TOPIC = KAFKA_TOPIC_LOGS
