"""
settings.py
-----------
Centralised configuration for LogSense AI.
All values are read from environment variables with safe defaults.
Never hardcode secrets or paths here — use .env file.

Usage:
    from config.settings import KafkaConfig, HDFSConfig, SparkConfig
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

_env = os.getenv


# ─── Dataset paths ────────────────────────────────────────────────────────────

class DatasetConfig:
    """Local paths to raw Loghub HDFS_v1 dataset files."""

    BASE_DIR: Path = Path(_env("DATASET_DIR", "data"))

    RAW_LOG: Path               = BASE_DIR / "HDFS.log"
    TEMPLATES_CSV: Path         = BASE_DIR / "preprocessed/HDFS.log_templates.csv"
    EVENT_TRACES_CSV: Path      = BASE_DIR / "preprocessed/Event_traces.csv"
    OCCURRENCE_MATRIX_CSV: Path = BASE_DIR / "preprocessed/Event_occurrence_matrix.csv"
    ANOMALY_LABELS_CSV: Path    = BASE_DIR / "preprocessed/anomaly_label.csv"

    @classmethod
    def validate(cls) -> None:
        """Raise FileNotFoundError if HDFS.log is missing."""
        if not cls.RAW_LOG.exists():
            raise FileNotFoundError(
                f"HDFS.log not found at {cls.RAW_LOG}. "
                f"Download from https://github.com/logpai/loghub"
            )


# ─── HDFS paths ───────────────────────────────────────────────────────────────

class HDFSConfig:
    """Hadoop HDFS directory layout for LogSense AI."""

    NAMENODE_HOST: str   = _env("HDFS_NAMENODE_HOST", "localhost")
    NAMENODE_PORT: int   = int(_env("HDFS_NAMENODE_PORT", "9000"))
    WEBHDFS_PORT: int  = int(_env("HDFS_WEBHDFS_PORT", "9870"))
    HDFS_USER: str = _env("HDFS_USER", "manojlinux")  # ← was "hadoop"

    # Base namespace — all LogSense data lives under /logsense/
    BASE_PATH: str       = "/logsense"

    # Sub-directories
    RAW_LOGS_PATH: str        = f"{BASE_PATH}/raw_logs"
    PARSED_LOGS_PATH: str     = f"{BASE_PATH}/parsed_logs"
    TEMPLATES_PATH: str       = f"{BASE_PATH}/templates"
    EVENT_SEQUENCES_PATH: str = f"{BASE_PATH}/event_sequences"
    PATTERNS_PATH: str        = f"{BASE_PATH}/patterns"
    FEATURES_PATH: str        = f"{BASE_PATH}/features"
    ANOMALIES_PATH: str       = f"{BASE_PATH}/anomalies"
    MODELS_PATH: str          = f"{BASE_PATH}/models"

    # All directories to create on setup
    ALL_DIRS: list[str] = [
        RAW_LOGS_PATH,
        PARSED_LOGS_PATH,
        TEMPLATES_PATH,
        EVENT_SEQUENCES_PATH,
        PATTERNS_PATH,
        FEATURES_PATH,
        ANOMALIES_PATH,
        MODELS_PATH,
    ]


# ─── Kafka ────────────────────────────────────────────────────────────────────

class KafkaConfig:
    """Kafka broker and topic configuration."""

    BOOTSTRAP_SERVERS: str = _env("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

    # Topics
    TOPIC_RAW_LOGS: str    = _env("KAFKA_TOPIC_RAW",    "hdfs-raw-logs")
    TOPIC_PARSED: str      = _env("KAFKA_TOPIC_PARSED", "hdfs-parsed-logs")
    TOPIC_ALERTS: str      = _env("KAFKA_TOPIC_ALERTS", "hdfs-anomaly-alerts")

    # Producer
    PRODUCER_RATE: int     = int(_env("KAFKA_PRODUCER_RATE", "1000"))

    # Consumer group
    CONSUMER_GROUP: str    = _env("KAFKA_CONSUMER_GROUP", "logsense-consumers")


# ─── Spark ────────────────────────────────────────────────────────────────────

class SparkConfig:
    """PySpark session configuration."""

    APP_NAME: str                  = "LogSense-AI"
    MASTER: str                    = _env("SPARK_MASTER", "local[*]")
    STREAMING_INTERVAL_SECS: int   = int(_env("SPARK_INTERVAL_SECS", "10"))
    CHECKPOINT_DIR: str            = _env(
        "SPARK_CHECKPOINT_DIR", "/tmp/logsense_checkpoint"
    )


# ─── Elasticsearch ────────────────────────────────────────────────────────────

class ESConfig:
    """Elasticsearch connection and index configuration."""

    HOST: str          = _env("ES_HOST", "localhost")
    PORT: int          = int(_env("ES_PORT", "9200"))
    USERNAME: str      = _env("ES_USERNAME", "elastic")
    PASSWORD: str      = _env("ES_PASSWORD", "")
    USE_SSL: bool      = _env("ES_USE_SSL", "false").lower() == "true"

    # Index names
    INDEX_LOGS: str     = _env("ES_INDEX_LOGS",     "logsense-logs")
    INDEX_ANOMALIES: str= _env("ES_INDEX_ANOMALIES","logsense-anomalies")
    INDEX_METRICS: str  = _env("ES_INDEX_METRICS",  "logsense-metrics")

    @classmethod
    def url(cls) -> str:
        scheme = "https" if cls.USE_SSL else "http"
        return f"{scheme}://{cls.HOST}:{cls.PORT}"


# ─── Mining ───────────────────────────────────────────────────────────────────

class MiningConfig:
    """Pattern mining algorithm hyperparameters."""

    # FP-Growth
    FP_GROWTH_MIN_SUPPORT: float    = float(_env("FP_MIN_SUPPORT",    "0.005"))
    FP_GROWTH_MIN_CONFIDENCE: float = float(_env("FP_MIN_CONFIDENCE", "0.5"))

    # PrefixSpan
    PREFIXSPAN_MIN_SUPPORT: float       = float(_env("PS_MIN_SUPPORT",    "0.005"))
    PREFIXSPAN_MAX_PATTERN_LENGTH: int  = int(_env("PS_MAX_PATTERN_LEN", "20"))

    # BisectingKMeans
    BKMEANS_K: int        = int(_env("BKMEANS_K",        "8"))
    BKMEANS_MAX_ITER: int = int(_env("BKMEANS_MAX_ITER", "20"))
    BKMEANS_SEED: int     = int(_env("BKMEANS_SEED",     "42"))


# ─── Anomaly Detection ────────────────────────────────────────────────────────

class AnomalyConfig:
    """Isolation Forest and threshold configuration."""

    # XGBoost / sklearn IF
    IF_N_ESTIMATORS: int        = int(_env("IF_N_ESTIMATORS",  "100"))
    _max_samples_raw = _env("IF_MAX_SAMPLES", "auto")
    IF_MAX_SAMPLES: int | str = (
        int(_max_samples_raw) if _max_samples_raw != "auto" else "auto"
    )
    IF_SUBSAMPLE: float         = float(_env("IF_SUBSAMPLE",   "0.8"))
    IF_RANDOM_STATE: int        = int(_env("IF_RANDOM_STATE",  "42"))

    # POT threshold
    POT_Q0: float               = float(_env("POT_Q0",          "0.90"))
    POT_RISK_LEVEL: float       = float(_env("POT_RISK_LEVEL",  "0.01"))
    FALLBACK_PERCENTILE: float  = float(_env("POT_FALLBACK_PCT","97.0"))


# ─── API ──────────────────────────────────────────────────────────────────────

class APIConfig:
    """FastAPI server configuration."""

    HOST: str       = _env("API_HOST",   "0.0.0.0")
    PORT: int       = int(_env("API_PORT", "8000"))
    RELOAD: bool    = _env("API_RELOAD", "false").lower() == "true"
    LOG_LEVEL: str  = _env("API_LOG_LEVEL", "info")

    # CORS — allow Kibana and React dashboard
    CORS_ORIGINS: list[str] = [
        o.strip()
        for o in _env(
            "CORS_ORIGINS",
            "http://localhost:5601,http://localhost:3000",
        ).split(",")
    ]