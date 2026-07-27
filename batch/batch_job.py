"""
batch_job.py
------------
Hourly batch orchestration job — the Lambda Architecture Batch Layer.

Triggered every hour by:
    Option A (simple):  Docker cron loop in docker-compose.yml  ← default
    Option B (advanced): Apache Airflow DAG in airflow/logsense_dag.py

What this job does each run:
    1. Read new parsed logs from HDFS (last 1 hour window)
    2. Run FP-Growth + PrefixSpan + BisectingKMeans on new blocks
    3. Build feature vectors for new blocks
    4. Score with pre-trained Isolation Forest model
    5. Write anomaly scores → HDFS + Elasticsearch
    6. Publish confirmed anomalies → Kafka alerts topic
    7. Retrain IF model if enough new data has accumulated (every 24 runs)
    8. Log batch run metadata (duration, counts, anomaly rate)

Design principles:
    - Idempotent: re-running the same hour window produces identical results
    - Incremental: only processes new blocks (watermark-based)
    - Non-blocking: streaming layer continues during batch run
    - Graceful degradation: if any step fails, logs error and continues

Run manually:
    python -m batch.batch_job --window-hours 1
    python -m batch.batch_job --window-hours 24  # full day backfill

Docker cron (from docker-compose.yml):
    command: >
      /bin/sh -c "while true; do
        python -m batch.batch_job --window-hours 1;
        sleep 3600;
      done"
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
from elasticsearch import Elasticsearch

from config.settings import AnomalyConfig, ESConfig, HDFSConfig, KafkaConfig
from utils.logger import get_logger

logger = get_logger(__name__)

# ─── Paths ────────────────────────────────────────────────────────────────────
RUN_METADATA_PATH    = Path("data/output/batch_run_history.jsonl")
WATERMARK_PATH       = Path("data/output/batch_watermark.json")
RETRAIN_EVERY_N_RUNS = 24   # Retrain IF model every 24 hourly runs


# ─── Watermark management ─────────────────────────────────────────────────────

class BatchWatermark:
    """
    Tracks the last successfully processed timestamp.
    Ensures each batch run only processes NEW data (no duplicates).

    Stored as JSON on local disk — persists across container restarts.
    In a production deployment this would live in Redis or HDFS.
    """

    def __init__(self, path: Path = WATERMARK_PATH):
        self.path = path
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            self._data = json.loads(self.path.read_text())
        else:
            self._data = {"last_processed_utc": None, "run_count": 0}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2))

    @property
    def last_processed_utc(self) -> datetime | None:
        ts = self._data.get("last_processed_utc")
        return datetime.fromisoformat(ts) if ts else None

    @property
    def run_count(self) -> int:
        return self._data.get("run_count", 0)

    def advance(self, new_timestamp: datetime) -> None:
        """Move watermark forward to new_timestamp and increment run count."""
        self._data["last_processed_utc"] = new_timestamp.isoformat()
        self._data["run_count"] = self.run_count + 1
        self._save()
        logger.info(
            "Watermark advanced to {} (run #{})",
            new_timestamp.isoformat(),
            self.run_count,
        )


# ─── Step 1: Load new blocks from HDFS ───────────────────────────────────────

def load_new_blocks(
    window_hours: int,
    watermark: BatchWatermark,
    spark,
) -> tuple[object, list[str]]:
    """
    Load parsed log blocks written to HDFS in the last `window_hours`.

    Reads from: hdfs://localhost:9000/logsense/parsed_logs/ (parquet, partitioned by log_date)
    Filters by: processed_at > watermark.last_processed_utc

    Returns:
        (blocks_df, block_ids)
        blocks_df:  Spark DataFrame of new parsed log rows
        block_ids:  list of new block_ids to process
    """
    from pyspark.sql import functions as F

    hdfs_parquet = f"hdfs://localhost:9000{HDFSConfig.PARSED_LOGS_PATH}"

    window_start = (
        (datetime.now(timezone.utc) - timedelta(hours=window_hours))
        if watermark.last_processed_utc is None
        else watermark.last_processed_utc
    )

    logger.info(
        "Loading new blocks from HDFS | window_start={}",
        window_start.isoformat(),
    )

    try:
        parsed_df = spark.read.parquet(hdfs_parquet)

        # Filter to window
        window_df = parsed_df.filter(
            F.col("processed_at") >= F.lit(window_start.isoformat())
        )

        new_block_ids = [
            row["block_id"]
            for row in window_df.select("block_id").distinct().collect()
            if row["block_id"] is not None
        ]

        logger.info(
            "Found {:,} new blocks in last {} hours",
            len(new_block_ids),
            window_hours,
        )

        return window_df, new_block_ids

    except Exception as exc:
        logger.error("Failed to load new blocks from HDFS: {}", exc)
        return None, []


# ─── Step 2: Build features for new blocks ───────────────────────────────────

def build_features_for_new_blocks(
    new_block_ids: list[str],
    spark,
) -> pd.DataFrame | None:
    """
    Build feature vectors for new blocks only.

    Strategy:
        - Load full occurrence matrix from HDFS (already has all blocks)
        - Filter to new_block_ids
        - Load existing mining scores for these blocks
        - Join and return feature DataFrame

    For very large windows (e.g., 24-hour backfill), re-runs the full
    mining pipeline to refresh all scores.

    Returns:
        feature_df: pandas DataFrame ready for IF scoring
                    None if no features could be built
    """
    if not new_block_ids:
        logger.info("No new blocks — skipping feature building.")
        return None

    logger.info("Building features for {:,} new blocks...", len(new_block_ids))

    try:
        # Load full feature matrix (already computed by previous full run)
        feature_csv = Path("data/output/block_features.csv")

        if not feature_csv.exists():
            logger.warning(
                "Full feature matrix not found. "
                "Running full feature builder..."
            )
            from anomaly.feature_builder import run_feature_builder
            run_feature_builder(spark)

        all_features = pd.read_csv(feature_csv)

        # Filter to new blocks
        new_features = all_features[
            all_features["block_id"].isin(set(new_block_ids))
        ].copy()

        if new_features.empty:
            logger.warning(
                "None of {:,} new block IDs found in feature matrix. "
                "These may be blocks not yet in the occurrence matrix.",
                len(new_block_ids),
            )
            return None

        logger.info(
            "Features built for {:,} / {:,} new blocks",
            len(new_features),
            len(new_block_ids),
        )
        return new_features

    except Exception as exc:
        logger.error("Feature building failed: {}", exc)
        return None


# ─── Step 3: Score new blocks ─────────────────────────────────────────────────

def score_new_blocks(
    new_features_df: pd.DataFrame,
) -> pd.DataFrame | None:
    """
    Score new blocks using the pre-trained IF model.
    If model doesn't exist, runs full batch training first.
    """
    from anomaly.isolation_forest import (
        IsolationForestModel,
        DynamicThreshold,
        run_batch_scoring,
        score_new_blocks as _score_fn,
    )

    model_pkl = Path("data/models/isolation_forest.pkl")
    threshold_json = Path("data/models/threshold.json")

    if not model_pkl.exists() or not threshold_json.exists():
        logger.warning("No trained model found. Running full batch scoring...")
        run_batch_scoring()
        return None  # Full scoring already saved results

    try:
        model = IsolationForestModel.load()
        threshold = DynamicThreshold.load()
        scored = _score_fn(new_features_df, model, threshold)
        logger.info(
            "Scored {:,} blocks | {:,} anomalies detected",
            len(scored),
            scored["is_anomaly"].sum(),
        )
        return scored
    except Exception as exc:
        logger.error("Scoring failed: {}", exc)
        return None


# ─── Step 4: Write results to Elasticsearch ───────────────────────────────────

def write_anomalies_to_es(scored_df: pd.DataFrame) -> int:
    """
    Write anomaly-flagged blocks to Elasticsearch index 'logsense-anomalies'.

    Only writes blocks where is_anomaly == 1.
    Returns count of documents written.
    """
    anomalies = scored_df[scored_df["is_anomaly"] == 1].copy()

    if anomalies.empty:
        logger.info("No anomalies to write to ES.")
        return 0

    try:
        es = Elasticsearch(
            ESConfig.url(),
            http_auth=(ESConfig.USERNAME, ESConfig.PASSWORD)
            if ESConfig.PASSWORD else None,
        )

        from elasticsearch.helpers import bulk

        docs = []
        run_ts = datetime.now(timezone.utc).isoformat()

        for _, row in anomalies.iterrows():
            docs.append({
                "_index": ESConfig.INDEX_ANOMALIES,
                "_id":    row["block_id"],
                "_source": {
                    "block_id":   row["block_id"],
                    "if_score":   float(row["if_score"]),
                    "is_anomaly": int(row["is_anomaly"]),
                    "threshold":  float(row.get("threshold", 0)),
                    "detected_at": run_ts,
                    "source":     "batch_layer",
                },
            })

        success, failed = bulk(es, docs, raise_on_error=False)
        logger.success(
            "ES write: {:,} anomaly docs | {:,} failed",
            success,
            len(failed) if isinstance(failed, list) else 0,
        )
        return success

    except Exception as exc:
        logger.error("ES anomaly write failed: {}", exc)
        return 0


# ─── Step 5: Publish confirmed anomalies to Kafka ─────────────────────────────

def publish_confirmed_anomalies(scored_df: pd.DataFrame) -> int:
    """
    Publish batch-confirmed anomaly block IDs to Kafka 'hdfs-anomaly-alerts'.
    These are the CONFIRMED anomalies (full IF score) vs streaming pre-screen.

    Returns count of messages published.
    """
    anomalies = scored_df[scored_df["is_anomaly"] == 1]
    if anomalies.empty:
        return 0

    try:
        from kafka import KafkaProducer

        producer = KafkaProducer(
            bootstrap_servers=KafkaConfig.BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

        count = 0
        for _, row in anomalies.iterrows():
            producer.send(
                KafkaConfig.TOPIC_ALERTS,
                value={
                    "block_id":   row["block_id"],
                    "if_score":   float(row["if_score"]),
                    "alert_type": "BATCH_CONFIRMED",
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            count += 1

        producer.flush()
        producer.close()

        logger.info("Published {:,} confirmed anomaly alerts to Kafka", count)
        return count

    except Exception as exc:
        logger.error("Kafka alert publish failed: {}", exc)
        return 0


# ─── Step 6: Model retraining (every 24 runs) ─────────────────────────────────

def maybe_retrain_model(watermark: BatchWatermark, spark) -> bool:
    """
    Retrain IF model every RETRAIN_EVERY_N_RUNS runs.

    Retraining rebuilds:
        1. Mining scores (FP, PrefixSpan, Clustering)
        2. Feature matrix
        3. IF model + threshold

    This keeps the model fresh as new log patterns emerge.
    Returns True if retraining happened.
    """
    if watermark.run_count % RETRAIN_EVERY_N_RUNS != 0:
        return False

    logger.info(
        "Run #{} — triggering scheduled model retraining...",
        watermark.run_count,
    )

    try:
        from mining.fp_growth import run_fp_growth_pipeline
        from mining.prefixspan import run_prefixspan_pipeline
        from mining.clustering import run_clustering_pipeline
        from anomaly.feature_builder import run_feature_builder
        from anomaly.isolation_forest import run_batch_scoring

        logger.info("[1/4] Rerunning FP-Growth...")
        run_fp_growth_pipeline(spark)

        logger.info("[2/4] Rerunning PrefixSpan...")
        run_prefixspan_pipeline(spark)

        logger.info("[3/4] Rerunning Clustering...")
        run_clustering_pipeline(spark)

        logger.info("[4/4] Rebuilding features + retraining IF model...")
        run_feature_builder(spark)
        run_batch_scoring()

        logger.success("Model retraining complete.")
        return True

    except Exception as exc:
        logger.error("Model retraining failed: {}", exc)
        return False


# ─── Batch run metadata ───────────────────────────────────────────────────────

def log_run_metadata(
    run_start: datetime,
    new_blocks: int,
    anomalies_detected: int,
    es_written: int,
    alerts_published: int,
    retrained: bool,
) -> None:
    """
    Append batch run metadata to JSONL file for auditability.
    Each line = one run record.
    """
    run_end = datetime.now(timezone.utc)
    elapsed = (run_end - run_start).total_seconds()

    record = {
        "run_at":            run_start.isoformat(),
        "elapsed_secs":      round(elapsed, 2),
        "new_blocks":        new_blocks,
        "anomalies_detected":anomalies_detected,
        "anomaly_rate":      round(anomalies_detected / new_blocks, 4) if new_blocks > 0 else 0,
        "es_written":        es_written,
        "alerts_published":  alerts_published,
        "model_retrained":   retrained,
    }

    RUN_METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RUN_METADATA_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")

    logger.success(
        "Batch run complete | {:,} new blocks | {:,} anomalies "
        "({:.2f}%) | {:.1f}s",
        new_blocks,
        anomalies_detected,
        record["anomaly_rate"] * 100,
        elapsed,
    )


# ─── Main batch job ───────────────────────────────────────────────────────────

def run_batch_job(window_hours: int = 1) -> None:
    """
    Full hourly batch job.

    Args:
        window_hours: How many hours of new data to process (default 1).
    """
    run_start = datetime.now(timezone.utc)
    logger.info(
        "=== LogSense AI — Batch Job START | {} ===",
        run_start.isoformat(),
    )

    # ── Build Spark session ───────────────────────────────────────────────────
    from pyspark.sql import SparkSession
    from config.settings import SparkConfig

    spark = (
        SparkSession.builder
        .appName(f"{SparkConfig.APP_NAME}-BatchJob")
        .master(SparkConfig.MASTER)
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.driver.memory", "4g")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    watermark = BatchWatermark()

    try:
        # Step 1: Load new blocks
        _, new_block_ids = load_new_blocks(window_hours, watermark, spark)

        # Step 2: Build features
        new_features_df = build_features_for_new_blocks(new_block_ids, spark)

        scored_df    = None
        n_anomalies  = 0
        es_written   = 0
        n_alerts     = 0

        if new_features_df is not None and not new_features_df.empty:

            # Step 3: Score
            scored_df = score_new_blocks(new_features_df)

            if scored_df is not None:
                n_anomalies = int(scored_df["is_anomaly"].sum())

                # Step 4: Write to ES
                es_written = write_anomalies_to_es(scored_df)

                # Step 5: Publish to Kafka
                n_alerts = publish_confirmed_anomalies(scored_df)

        # Step 6: Maybe retrain
        retrained = maybe_retrain_model(watermark, spark)

        # Step 7: Advance watermark
        watermark.advance(run_start)

        # Log metadata
        log_run_metadata(
            run_start    = run_start,
            new_blocks   = len(new_block_ids),
            anomalies_detected = n_anomalies,
            es_written   = es_written,
            alerts_published = n_alerts,
            retrained    = retrained,
        )

    except Exception as exc:
        logger.error("Batch job failed: {}", exc)
        raise

    finally:
        spark.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LogSense AI Hourly Batch Job")
    parser.add_argument(
        "--window-hours",
        type=int,
        default=1,
        help="Hours of data to process (default: 1)",
    )
    args = parser.parse_args()
    run_batch_job(window_hours=args.window_hours)