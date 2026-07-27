"""
spark_streaming.py
------------------
Core real-time processing engine — Step 3 of the pipeline.

Flow:
    Kafka (hdfs-raw-logs)
        → parse JSON envelope
        → regex-extract log fields
        → map content → EventID (broadcast template lookup)
        → extract BlockID
        → write structured logs → HDFS (parquet) + Elasticsearch
        → real-time anomaly pre-screening (rule-based, fast)
        → flag high-risk blocks → Kafka (hdfs-anomaly-alerts)

NOTE:
    Full anomaly scoring (Isolation Forest) runs in batch/batch_job.py hourly.
    This streaming job does fast rule-based pre-screening only:
        - High-risk EventID detected (E9/E11 class)
        - Block has repeated failure events in current window
    Deep scoring happens in the batch layer.

Run:
    python -m processing.spark_streaming
"""

from __future__ import annotations

import json
import re
from typing import Iterator

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
    LongType,
    TimestampType,
    IntegerType,
    BooleanType,
    ArrayType,
    FloatType,
)

from config.settings import (
    ESConfig,
    HDFSConfig,
    KafkaConfig,
    SparkConfig,
    DatasetConfig,
)
from parsing.template_mapper import get_mapper
from utils.logger import get_logger

logger = get_logger(__name__)


# ─── High-risk EventID sets (for real-time pre-screening) ────────────────────
# Derived from Loghub HDFS_v1 paper — these events correlate with anomalies

# Events that commonly appear in anomalous sequences
HIGH_RISK_EVENT_IDS = {
    "E9",   # Got exception while serving
    "E11",  # Packet exception
    "E26",  # DataNode lost
    "E14",  # Error accessing
    "E21",  # Received block exception
}

# Minimum consecutive high-risk events before raising a real-time alert
HIGH_RISK_THRESHOLD = 2


# ─── Schema Definitions ──────────────────────────────────────────────────────

# Schema of JSON envelope from Kafka producer
_KAFKA_VALUE_SCHEMA = StructType([
    StructField("line_no", LongType(), True),
    StructField("ingested_at", StringType(), True),
    StructField("raw", StringType(), True),
])

# Schema of a fully parsed, structured log record
PARSED_LOG_SCHEMA = StructType([
    StructField("line_no", LongType(), False),
    StructField("log_date", StringType(), True),    # "081109"
    StructField("log_time", StringType(), True),    # "203518"
    StructField("pid", StringType(), True),
    StructField("level", StringType(), True),
    StructField("component", StringType(), True),
    StructField("content", StringType(), True),
    StructField("block_id", StringType(), True),    # "blk_-1608999687919862906"
    StructField("event_id", StringType(), True),    # "E5"
    StructField("ingested_at", StringType(), True),
    StructField("raw", StringType(), True),
])

# Schema for real-time alert messages pushed to Kafka
ALERT_SCHEMA = StructType([
    StructField("block_id", StringType(), False),
    StructField("trigger_event", StringType(), True),
    StructField("consecutive_risk_count", IntegerType(), True),
    StructField("alert_type", StringType(), True),
    StructField("detected_at", StringType(), True),
])


# ─── Regex patterns ──────────────────────────────────────────────────────────

# Matches: "081109 203518 143 INFO dfs.DataNode$DataXceiver: <content>"
_LOG_LINE_REGEX = re.compile(
    r"^(?P<date>\d{6})\s+"
    r"(?P<time>\d{6})\s+"
    r"(?P<pid>\d+)\s+"
    r"(?P<level>\w+)\s+"
    r"(?P<component>\S+):\s+"
    r"(?P<content>.+)$"
)

# Matches HDFS Block IDs like blk_-1608999687919862906
_BLOCK_ID_REGEX = re.compile(r"(blk_-?\d+)")


def _parse_raw_line(raw: str) -> dict | None:
    """
    Parse a single raw HDFS log line into structured fields.
    Returns None if the line doesn't match expected format.
    """
    match = _LOG_LINE_REGEX.match(raw.strip())
    if not match:
        return None
    return {
        "log_date": match.group("date"),
        "log_time": match.group("time"),
        "pid": match.group("pid"),
        "level": match.group("level"),
        "component": match.group("component"),
        "content": match.group("content"),
    }


def _extract_block_id(content: str) -> str | None:
    """Extract HDFS block ID from log content. Returns first match or None."""
    match = _BLOCK_ID_REGEX.search(content)
    return match.group(1) if match else None


# ─── Spark Session builder ────────────────────────────────────────────────────

def _build_spark_session() -> SparkSession:
    """
    Build and return a SparkSession configured for:
    - Kafka structured streaming
    - Elasticsearch connector
    - HDFS write (parquet)
    """
    logger.info("Building SparkSession: master={}", SparkConfig.MASTER)

    spark = (
        SparkSession.builder
        .appName(SparkConfig.APP_NAME)
        .master(SparkConfig.MASTER)
        # ── Kafka source ──────────────────────────────────────────────────────
        .config(
            "spark.jars.packages",
            ",".join([
                "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1",
                "org.elasticsearch:elasticsearch-spark-30_2.12:8.13.0",
            ]),
        )
        # ── Elasticsearch connector ───────────────────────────────────────────
        .config("es.nodes", ESConfig.HOST)
        .config("es.port", str(ESConfig.PORT))
        .config("es.index.auto.create", "true")
        .config("es.nodes.wan.only", "true")
        # ── Streaming performance ─────────────────────────────────────────────
        .config("spark.streaming.backpressure.enabled", "true")
        .config("spark.sql.shuffle.partitions", "8")   # reduce for local mode
        .config("spark.sql.streaming.checkpointLocation", "/tmp/logsense_checkpoint")
        # ── Serialization ─────────────────────────────────────────────────────
        .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
        # ── Logging ───────────────────────────────────────────────────────────
        .config("spark.driver.extraJavaOptions", "-Dlog4j.logLevel=WARN")
        .getOrCreate()
    )

    # Reduce Spark's own verbose logging
    spark.sparkContext.setLogLevel("WARN")

    logger.success("SparkSession ready: {}", spark.version)
    return spark


# ─── Kafka source ─────────────────────────────────────────────────────────────

def _read_kafka_stream(spark: SparkSession) -> DataFrame:
    """
    Create a streaming DataFrame from Kafka topic 'hdfs-raw-logs'.

    Each row from Kafka has:
        key     (binary)
        value   (binary) — our JSON envelope: {line_no, ingested_at, raw}
        topic, partition, offset, timestamp, timestampType
    """
    logger.info(
        "Subscribing to Kafka topic: {} at {}",
        KafkaConfig.TOPIC_RAW_LOGS,
        KafkaConfig.BOOTSTRAP_SERVERS,
    )

    return (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", KafkaConfig.BOOTSTRAP_SERVERS)
        .option("subscribe", KafkaConfig.TOPIC_RAW_LOGS)
        .option("startingOffsets", "latest")        # real-time: only new messages
        .option("maxOffsetsPerTrigger", 50000)      # process 50k rows per micro-batch
        .option("failOnDataLoss", "false")          # tolerate partition rebalance
        .load()
    )


# ─── Parsing UDF ─────────────────────────────────────────────────────────────

def _build_parsing_udf(spark: SparkSession):
    """
    Build a Spark UDF that:
    1. Parses the raw log line (regex)
    2. Extracts BlockID
    3. Maps content → EventID using broadcast template map

    The template map is broadcast to all executors once
    and reused for every row — O(1) lookup per message.

    Returns the UDF function (registered for use in withColumn).
    """
    # Load and serialize the template map
    # IMPORTANT: We pass pattern strings, not compiled re.Pattern objects.
    # Compiled patterns are NOT picklable by Spark.
    # Workers compile them lazily on first use.
    mapper = get_mapper()
    serializable_map = mapper.get_serializable_map()
    high_risk_ids = HIGH_RISK_EVENT_IDS

    logger.info(
        "Broadcasting template map: {} patterns to Spark workers",
        len(serializable_map),
    )

    # Broadcast the serializable map
    broadcast_map = spark.sparkContext.broadcast(serializable_map)

    # ── Output schema ─────────────────────────────────────────────────────────
    output_schema = StructType([
        StructField("log_date", StringType()),
        StructField("log_time", StringType()),
        StructField("pid", StringType()),
        StructField("level", StringType()),
        StructField("component", StringType()),
        StructField("content", StringType()),
        StructField("block_id", StringType()),
        StructField("event_id", StringType()),
        StructField("is_high_risk", BooleanType()),
    ])

    # ── Worker-side compiled patterns (lazily initialized per executor) ───────
    _worker_patterns: list[tuple[re.Pattern, str]] | None = None

    def _get_worker_patterns() -> list[tuple[re.Pattern, str]]:
        """
        Compile regex patterns on the worker side.
        Called once per executor process (lazy init).
        """
        nonlocal _worker_patterns
        if _worker_patterns is None:
            raw_patterns = broadcast_map.value
            _worker_patterns = [
                (re.compile(pattern_str, re.IGNORECASE), event_id)
                for pattern_str, event_id in raw_patterns
            ]
        return _worker_patterns

    def _match_event_id(content: str) -> str:
        """Match content to EventID using compiled patterns."""
        patterns = _get_worker_patterns()
        for pattern, event_id in patterns:
            if pattern.search(content):
                return event_id
        return "E_UNKNOWN"

    # ── The actual UDF function ───────────────────────────────────────────────
    def parse_log_line(raw: str):
        """
        Spark UDF entry point.
        Takes a raw log string, returns a struct with parsed fields.
        """
        if raw is None:
            return None

        # 1. Regex parse
        match = re.match(
            r"^(?P<date>\d{6})\s+(?P<time>\d{6})\s+(?P<pid>\d+)\s+"
            r"(?P<level>\w+)\s+(?P<component>\S+):\s+(?P<content>.+)$",
            raw.strip(),
        )
        if not match:
            return None

        content = match.group("content")

        # 2. Extract BlockID
        block_match = re.search(r"(blk_-?\d+)", content)
        block_id = block_match.group(1) if block_match else None

        # 3. Map to EventID
        event_id = _match_event_id(content)

        # 4. High-risk flag
        is_high_risk = event_id in high_risk_ids

        return (
            match.group("date"),
            match.group("time"),
            match.group("pid"),
            match.group("level"),
            match.group("component"),
            content,
            block_id,
            event_id,
            is_high_risk,
        )

    return F.udf(parse_log_line, output_schema)


# ─── DataFrame transformations ────────────────────────────────────────────────

def _parse_kafka_stream(
    raw_stream: DataFrame,
    parse_udf,
) -> DataFrame:
    """
    Transform raw Kafka stream into structured log DataFrame.

    Steps:
    1. Decode binary Kafka value → JSON string
    2. Parse JSON envelope → (line_no, ingested_at, raw)
    3. Apply parse_log_line UDF → structured fields
    4. Flatten struct columns
    5. Add processing timestamp
    """

    # 1. Decode Kafka binary value to string
    value_str = raw_stream.select(
        F.col("value").cast("string").alias("value_str"),
        F.col("timestamp").alias("kafka_timestamp"),
    )

    # 2. Parse JSON envelope
    envelope = value_str.select(
        F.from_json(
            F.col("value_str"),
            _KAFKA_VALUE_SCHEMA,
        ).alias("envelope"),
        F.col("kafka_timestamp"),
    ).select(
        F.col("envelope.line_no").alias("line_no"),
        F.col("envelope.ingested_at").alias("ingested_at"),
        F.col("envelope.raw").alias("raw"),
        F.col("kafka_timestamp"),
    )

    # 3. Apply parsing UDF — parse raw → structured fields
    parsed = envelope.withColumn(
        "parsed",
        parse_udf(F.col("raw")),
    )

    # 4. Flatten struct into individual columns
    structured = parsed.select(
        F.col("line_no"),
        F.col("ingested_at"),
        F.col("kafka_timestamp"),
        F.col("raw"),
        F.col("parsed.log_date").alias("log_date"),
        F.col("parsed.log_time").alias("log_time"),
        F.col("parsed.pid").alias("pid"),
        F.col("parsed.level").alias("level"),
        F.col("parsed.component").alias("component"),
        F.col("parsed.content").alias("content"),
        F.col("parsed.block_id").alias("block_id"),
        F.col("parsed.event_id").alias("event_id"),
        F.col("parsed.is_high_risk").alias("is_high_risk"),
    )

    # 5. Filter out unparseable lines (parsed struct is null)
    # and lines without a block ID (non-block events — not useful for mining)
    structured = structured.filter(
        F.col("log_date").isNotNull() &
        F.col("block_id").isNotNull()
    )

    # 6. Add processing metadata
    structured = structured.withColumn(
        "processed_at",
        F.current_timestamp(),
    )

    return structured


# ─── Sink: HDFS (Parquet) ────────────────────────────────────────────────────

def _write_to_hdfs(structured_df: DataFrame) -> object:
    """
    Write structured log stream to HDFS as partitioned Parquet files.

    Partitioned by log_date → efficient batch layer reads by date.
    Uses 'append' output mode — new files added each micro-batch.

    HDFS path: /logsense/parsed_logs/log_date=XXXXXX/
    """
    hdfs_path = f"hdfs://localhost:9000{HDFSConfig.PARSED_LOGS_PATH}"

    logger.info("Starting HDFS sink → {}", hdfs_path)

    return (
        structured_df
        # Select only columns to persist (drop kafka metadata)
        .select(
            "line_no", "log_date", "log_time", "pid",
            "level", "component", "content",
            "block_id", "event_id", "is_high_risk",
            "ingested_at", "processed_at",
        )
        .writeStream
        .format("parquet")
        .option("path", hdfs_path)
        .option(
            "checkpointLocation",
            "/tmp/logsense_checkpoint/hdfs_sink",
        )
        .partitionBy("log_date")        # partition by date for batch reads
        .outputMode("append")
        .trigger(
            processingTime=f"{SparkConfig.STREAMING_INTERVAL_SECS} seconds"
        )
        .start()
    )


# ─── Sink: Elasticsearch ──────────────────────────────────────────────────────

def _write_to_elasticsearch(structured_df: DataFrame) -> object:
    """
    Write structured log stream to Elasticsearch index 'logsense-logs'.
    Uses foreachBatch to write each micro-batch using ES connector.

    ES document format:
    {
        "block_id": "blk_xxx",
        "event_id": "E5",
        "component": "DataNode$DataXceiver",
        "level": "INFO",
        "log_date": "081109",
        "log_time": "203518",
        "is_high_risk": false,
        "ingested_at": "...",
        "processed_at": "..."
    }
    """
    es_index = ESConfig.INDEX_LOGS

    def _write_batch_to_es(batch_df: DataFrame, batch_id: int) -> None:
        """Called once per micro-batch. Writes to ES using connector."""
        count = batch_df.count()
        if count == 0:
            return

        logger.info(
            "Writing batch {} to ES index '{}': {:,} records",
            batch_id,
            es_index,
            count,
        )

        try:
            (
                batch_df
                .select(
                    "block_id", "event_id", "component", "level",
                    "log_date", "log_time", "content",
                    "is_high_risk", "ingested_at", "processed_at",
                )
                .write
                .format("org.elasticsearch.spark.sql")
                .option("es.resource", es_index)
                .option("es.mapping.id", "block_id")   # block_id as doc ID
                .option("es.write.operation", "upsert")
                .mode("append")
                .save()
            )
            logger.debug("Batch {} written to ES successfully.", batch_id)

        except Exception as exc:
            logger.error(
                "ES write failed for batch {}: {}", batch_id, exc
            )
            # Don't re-raise — allow streaming to continue
            # Failed batches will be retried via checkpoint

    return (
        structured_df.writeStream
        .foreachBatch(_write_batch_to_es)
        .option(
            "checkpointLocation",
            "/tmp/logsense_checkpoint/es_sink",
        )
        .outputMode("append")
        .trigger(
            processingTime=f"{SparkConfig.STREAMING_INTERVAL_SECS} seconds"
        )
        .start()
    )


# ─── Sink: Real-Time Alert Publisher ─────────────────────────────────────────

def _write_alerts_to_kafka(structured_df: DataFrame, spark: SparkSession) -> object:
    """
    Real-time pre-screening: detect high-risk blocks and publish alerts.

    Logic (fast, rule-based — NOT the final Isolation Forest score):
        Within each 1-minute window, if a block has >= HIGH_RISK_THRESHOLD
        high-risk events → publish an early alert to Kafka.

    This is the "Speed Layer" alert for the dashboard.
    The full Isolation Forest score comes from the hourly Batch Layer.
    """

    def _publish_alerts(batch_df: DataFrame, batch_id: int) -> None:
        """
        For each micro-batch:
        1. Filter high-risk events
        2. Group by block_id, count consecutive high-risk events
        3. Publish blocks exceeding threshold to alert topic
        """
        if batch_df.rdd.isEmpty():
            return

        # Count high-risk events per block in this micro-batch
        risk_counts = (
            batch_df
            .filter(F.col("is_high_risk") == True)
            .groupBy("block_id")
            .agg(
                F.count("*").alias("risk_event_count"),
                F.first("event_id").alias("trigger_event"),
                F.first("component").alias("component"),
                F.first("processed_at").alias("detected_at"),
            )
            .filter(F.col("risk_event_count") >= HIGH_RISK_THRESHOLD)
        )

        alert_rows = risk_counts.collect()

        if not alert_rows:
            return

        from kafka import KafkaProducer as _KProducer
        producer = _KProducer(
            bootstrap_servers=KafkaConfig.BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

        for row in alert_rows:
            alert = {
                "block_id": row["block_id"],
                "trigger_event": row["trigger_event"],
                "risk_event_count": row["risk_event_count"],
                "component": row["component"],
                "alert_type": "REALTIME_PRESCREENING",
                "detected_at": str(row["detected_at"]),
                "note": "Preliminary alert. Confirm with batch Isolation Forest score.",
            }

            producer.send(KafkaConfig.TOPIC_ALERTS, value=alert)
            logger.warning(
                "ALERT: block_id={} | {} high-risk events | trigger={}",
                row["block_id"],
                row["risk_event_count"],
                row["trigger_event"],
            )

        producer.flush()
        producer.close()

    return (
        structured_df.writeStream
        .foreachBatch(_publish_alerts)
        .option(
            "checkpointLocation",
            "/tmp/logsense_checkpoint/alert_sink",
        )
        .outputMode("append")
        .trigger(
            processingTime=f"{SparkConfig.STREAMING_INTERVAL_SECS} seconds"
        )
        .start()
    )


# ─── Main streaming job ───────────────────────────────────────────────────────

def run_streaming_job() -> None:
    """
    Start all streaming queries:
    1. HDFS parquet sink       — cold storage, batch layer input
    2. Elasticsearch sink      — hot storage, Kibana backend
    3. Kafka alert sink        — real-time pre-screening alerts

    All three run in parallel (separate streaming queries).
    Await termination — runs until manually stopped or error.
    """
    logger.info("=== LogSense AI — Spark Structured Streaming ===")

    spark = _build_spark_session()

    # Build parsing UDF (broadcasts template map to all workers)
    parse_udf = _build_parsing_udf(spark)

    # 1. Read from Kafka
    raw_stream = _read_kafka_stream(spark)
    logger.info("Kafka stream created. Starting parsing pipeline...")

    # 2. Parse and structure
    structured_stream = _parse_kafka_stream(raw_stream, parse_udf)

    # 3. Start all sinks in parallel
    logger.info("Starting HDFS sink...")
    hdfs_query = _write_to_hdfs(structured_stream)

    logger.info("Starting Elasticsearch sink...")
    es_query = _write_to_elasticsearch(structured_stream)

    logger.info("Starting Kafka alert sink (real-time prescreening)...")
    alert_query = _write_alerts_to_kafka(structured_stream, spark)

    logger.success(
        "All streaming queries started. "
        "Processing every {} seconds. Waiting for data...",
        SparkConfig.STREAMING_INTERVAL_SECS,
    )

    # Monitor query status periodically
    import time

    try:
        while True:
            time.sleep(30)

            for name, query in [
                ("HDFS", hdfs_query),
                ("Elasticsearch", es_query),
                ("Alerts", alert_query),
            ]:
                if not query.isActive:
                    exc = query.exception()
                    logger.error(
                        "Streaming query '{}' stopped unexpectedly: {}",
                        name,
                        exc,
                    )
                    # Attempt to restart — raise so the process restarts
                    raise RuntimeError(
                        f"Streaming query '{name}' died: {exc}"
                    )

                progress = query.lastProgress
                if progress:
                    input_rate = progress.get("inputRowsPerSecond", 0)
                    processed = progress.get("numInputRows", 0)
                    logger.info(
                        "Query '{}' | {:.0f} rows/sec | {} rows in last batch",
                        name,
                        input_rate or 0,
                        processed or 0,
                    )

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Stopping all queries...")

    finally:
        for name, query in [
            ("HDFS", hdfs_query),
            ("Elasticsearch", es_query),
            ("Alerts", alert_query),
        ]:
            if query.isActive:
                query.stop()
                logger.info("Stopped query: {}", name)

        spark.stop()
        logger.success("SparkSession stopped. Streaming job complete.")


if __name__ == "__main__":
    run_streaming_job()