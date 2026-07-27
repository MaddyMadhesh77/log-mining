"""
kafka_producer.py
-----------------
Step 2 of the pipeline: Stream raw log lines from HDFS → Kafka topic.

Reads HDFS.log from Hadoop HDFS (NOT local disk) using chunked streaming.
Sends each line to Kafka topic 'hdfs-raw-logs'.
Simulates real-time ingestion at a controlled rate.

Rate is controlled by KAFKA_PRODUCER_RATE in .env (lines per second).

Run:
    python -m ingestion.kafka_producer
"""

from __future__ import annotations

import json
import signal
import time
from datetime import datetime, timezone
from typing import Any

from kafka import KafkaProducer
from kafka.errors import KafkaError, NoBrokersAvailable

from config.settings import HDFSConfig, KafkaConfig
from utils.hdfs_client import read_lines
from utils.logger import get_logger

logger = get_logger(__name__)

# HDFS source path
HDFS_SOURCE_PATH = f"{HDFSConfig.RAW_LOGS_PATH}/HDFS.log"

# Graceful shutdown flag
_shutdown = False


def _signal_handler(signum, frame):
    global _shutdown
    logger.warning("Shutdown signal received. Finishing current batch...")
    _shutdown = True


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def _build_producer() -> KafkaProducer:
    """
    Build and return a KafkaProducer with:
    - JSON serialization for the value
    - Retry and batch configuration for throughput
    """
    logger.info(
        "Connecting to Kafka broker: {}", KafkaConfig.BOOTSTRAP_SERVERS
    )

    try:
        producer = KafkaProducer(
            bootstrap_servers=KafkaConfig.BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            # Throughput tuning
            batch_size=65536,           # 64KB batch
            linger_ms=10,               # wait up to 10ms to fill batch
            compression_type="gzip",    # compress batches
            # Reliability
            acks="all",                 # wait for all replicas
            retries=5,
            retry_backoff_ms=300,
            # Buffer
            buffer_memory=67108864,     # 64MB send buffer
            max_block_ms=10000,
        )
        logger.success("Kafka producer connected.")
        return producer

    except NoBrokersAvailable as exc:
        logger.error(
            "No Kafka brokers available at {}. "
            "Is Kafka running? Error: {}",
            KafkaConfig.BOOTSTRAP_SERVERS,
            exc,
        )
        raise


def _on_send_error(exc: Exception) -> None:
    """Callback for failed message sends."""
    logger.error("Kafka send error: {}", exc)


def _build_message(raw_line: str, line_number: int) -> dict[str, Any]:
    """
    Wrap a raw log line in a JSON envelope with metadata.

    The envelope allows Spark Streaming to track ingestion time
    and line number without modifying the raw log content.

    Message format:
    {
        "line_no":    123456,
        "ingested_at": "2026-04-02T00:00:00Z",
        "raw":        "<original log line>"
    }
    """
    return {
        "line_no": line_number,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "raw": raw_line,
    }


def stream_logs(
    hdfs_path: str = HDFS_SOURCE_PATH,
    rate_per_sec: int = KafkaConfig.PRODUCER_RATE,
    max_lines: int | None = None,
) -> None:
    """
    Main streaming loop.

    Reads lines from HDFS, wraps in JSON envelope, sends to Kafka.
    Rate-limits to `rate_per_sec` messages per second.

    Args:
        hdfs_path:    HDFS path to read from
        rate_per_sec: Target lines per second (0 = no limit)
        max_lines:    Stop after N lines (None = stream entire file)
    """
    producer = _build_producer()
    topic = KafkaConfig.TOPIC_RAW_LOGS

    logger.info(
        "Starting stream: HDFS:{} → Kafka:{} at ~{} lines/sec",
        hdfs_path,
        topic,
        rate_per_sec,
    )

    sleep_interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0
    line_count = 0
    sent_count = 0
    error_count = 0
    start_time = time.perf_counter()
    last_log_time = start_time

    try:
        for raw_line in read_lines(hdfs_path):
            if _shutdown:
                logger.info("Shutdown flag set. Stopping producer.")
                break

            if max_lines and line_count >= max_lines:
                logger.info("Reached max_lines limit: {}", max_lines)
                break

            line_count += 1

            # Skip blank lines
            if not raw_line.strip():
                continue

            message = _build_message(raw_line.strip(), line_count)

            # Send to Kafka (async with error callback)
            producer.send(
                topic,
                value=message,
                key=str(line_count).encode("utf-8"),
            ).add_errback(_on_send_error)

            sent_count += 1

            # Rate limiting
            if sleep_interval > 0:
                time.sleep(sleep_interval)

            # Progress log every 100k lines
            now = time.perf_counter()
            if now - last_log_time >= 10.0:
                elapsed = now - start_time
                actual_rate = sent_count / elapsed if elapsed > 0 else 0
                logger.info(
                    "Progress: {:,} lines sent | {:.0f} lines/sec | "
                    "{:,} errors | elapsed: {:.1f}s",
                    sent_count,
                    actual_rate,
                    error_count,
                    elapsed,
                )
                last_log_time = now

    except Exception as exc:
        logger.error("Streaming interrupted at line {}: {}", line_count, exc)
        raise
    finally:
        logger.info("Flushing remaining messages to Kafka...")
        producer.flush(timeout=30)
        producer.close()

        elapsed = time.perf_counter() - start_time
        logger.success(
            "Stream complete. Sent {:,} lines in {:.1f}s ({:.0f} lines/sec)",
            sent_count,
            elapsed,
            sent_count / elapsed if elapsed > 0 else 0,
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Stream HDFS logs to Kafka")
    parser.add_argument(
        "--rate",
        type=int,
        default=KafkaConfig.PRODUCER_RATE,
        help="Lines per second to stream (default from .env)",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=None,
        help="Stop after N lines (for testing)",
    )
    parser.add_argument(
        "--hdfs-path",
        type=str,
        default=HDFS_SOURCE_PATH,
        help="HDFS path to stream from",
    )
    args = parser.parse_args()

    stream_logs(
        hdfs_path=args.hdfs_path,
        rate_per_sec=args.rate,
        max_lines=args.max_lines,
    )