"""
Global constants for the Log Pattern Mining project.
Includes ML model paths, batch sizes, and other configuration constants.
"""

import os

# Project paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
MODELS_DIR = os.path.join(PROJECT_ROOT, 'models')
RESULTS_DIR = os.path.join(DATA_DIR, 'results')

# ML Model paths
ANOMALY_DETECTOR_MODEL = os.path.join(MODELS_DIR, 'anomaly_detector.h5')
DEEP_LEARNING_MODEL = os.path.join(MODELS_DIR, 'deep_learning_detector.h5')

# Data paths
RAW_LOGS_DIR = os.path.join(DATA_DIR, 'raw_logs')
PARSED_LOGS_DIR = os.path.join(DATA_DIR, 'parsed_logs')
PROCESSED_LOGS_DIR = os.path.join(DATA_DIR, 'processed_logs')

# Processing parameters
BATCH_SIZE = 1000
WINDOW_SIZE = 50
MIN_SUPPORT = 0.05
MIN_CONFIDENCE = 0.7

# Kafka parameters
KAFKA_BROKERS = ['localhost:9092']
KAFKA_TOPIC_LOGS = 'system_logs'
KAFKA_CONSUMER_GROUP = 'log_miners'

# Spark parameters
SPARK_MASTER = 'local[*]'
SPARK_APP_NAME = 'LogPatternMining'
NUM_PARTITIONS = 4

# Elasticsearch parameters
ELASTICSEARCH_HOSTS = ['localhost:9200']
ELASTICSEARCH_INDEX_PREFIX = 'logs'

# HDFS parameters
HDFS_NAMENODE = 'hdfs://localhost:9000'
HDFS_BASE_PATH = '/logs'

# Logging
LOG_LEVEL = 'INFO'
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

# Anomaly Detection thresholds
ANOMALY_THRESHOLD = 0.8
STATISTICAL_ANOMALY_THRESHOLD = 3.0  # Standard deviations

# Pattern Mining
MIN_PATTERN_LENGTH = 2
MAX_PATTERN_LENGTH = 10
