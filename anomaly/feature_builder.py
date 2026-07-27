"""
feature_builder.py
------------------
Joins outputs from all three mining modules into a single
per-block feature matrix for Isolation Forest.

Input sources (all produced by Part 4 mining pipelines):
    1. FP-Growth      → fp_rarity_score          (float 0–1)
    2. PrefixSpan     → seq_deviation_score       (float 0–1)
    3. BisectingKMeans→ cluster_outlier_score      (float 0–1)
                       cluster_id                 (int 0–7)
    4. Event_occurrence_matrix.csv → E1..E29 counts (int, normalized)
    5. Derived features from raw log stats

Final feature vector: 32 features per block.

Feature catalog (32 total):
    ── Mining scores (3) ───────────────────────────────────
    fp_rarity_score             FP-Growth rarity (0–1)
    seq_deviation_score         PrefixSpan deviation (0–1)
    cluster_outlier_score       BisectingKMeans distance (0–1)

    ── Cluster context (1) ──────────────────────────────────
    cluster_id                  Cluster assignment (0–7)

    ── Event occurrence counts (29) ─────────────────────────
    E1 .. E29                   Count of each EventID in block
                                (log1p normalized to reduce skew)

    ── Block-level log stats (3) ────────────────────────────
    total_events                Total events in block
    unique_event_count          Count of distinct event types
    log_span_secs               Time span from first to last event

    NOTE: total = 3 + 1 + 29 - 1 (E29 often empty, dropped) + 3 = 35
          We drop constant/zero-variance features → final ~32 features.
          Exact count printed at runtime.

Run:
    python -m anomaly.feature_builder
"""

from __future__ import annotations

from pyexpat import features
import time
from pathlib import Path

import numpy as np
import pandas as pd
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DoubleType,
    IntegerType,
    StructField,
    StructType,
    StringType,
    FloatType,
)

from config.settings import DatasetConfig, HDFSConfig, SparkConfig
from utils.logger import get_logger

logger = get_logger(__name__)

# ─── I/O paths ────────────────────────────────────────────────────────────────
HDFS_FP_SCORES     = f"hdfs://localhost:9000{HDFSConfig.PATTERNS_PATH}/fp_growth/block_scores"
HDFS_SEQ_SCORES    = f"hdfs://localhost:9000{HDFSConfig.PATTERNS_PATH}/prefixspan/block_scores"
HDFS_CLUSTER_SCORES= f"hdfs://localhost:9000{HDFSConfig.PATTERNS_PATH}/clustering/block_scores"
HDFS_FEATURE_OUT   = f"hdfs://localhost:9000{HDFSConfig.FEATURES_PATH}/block_features"

LOCAL_FEATURE_CSV  = Path("data/output/block_features.csv")
LOCAL_LABELS_CSV   = DatasetConfig.ANOMALY_LABELS_CSV

# Features to drop due to typical zero-variance in HDFS_v1
ZERO_VARIANCE_EVENTS = {"E7", "E8", "E13", "E15"}


# ─── Spark Session ────────────────────────────────────────────────────────────

def _get_spark() -> SparkSession:
    s = SparkSession.getActiveSession()
    if s:
        return s
    return (
        SparkSession.builder
        .appName(f"{SparkConfig.APP_NAME}-FeatureBuilder")
        .master(SparkConfig.MASTER)
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.driver.memory", "4g")
        .getOrCreate()
    )


# ─── Load mining scores ───────────────────────────────────────────────────────

def _load_fp_scores(spark: SparkSession) -> DataFrame:
    """Load FP-Growth block rarity scores."""
    try:
        df = spark.read.parquet(HDFS_FP_SCORES)
        logger.info("FP scores loaded from HDFS: {:,} rows", df.count())
        return df.select("block_id", "fp_rarity_score")
    except Exception:
        logger.warning("HDFS FP scores not found. Running FP-Growth now...")
        from mining.fp_growth import run_fp_growth_pipeline
        fp_df = run_fp_growth_pipeline(spark)
        return fp_df.select("block_id", "fp_rarity_score")


def _load_seq_scores(spark: SparkSession) -> DataFrame:
    """Load PrefixSpan sequence deviation scores."""
    try:
        df = spark.read.parquet(HDFS_SEQ_SCORES)
        logger.info("Seq scores loaded from HDFS: {:,} rows", df.count())
        return df.select("block_id", "seq_deviation_score")
    except Exception:
        logger.warning("HDFS seq scores not found. Running PrefixSpan now...")
        from mining.prefixspan import run_prefixspan_pipeline
        seq_df = run_prefixspan_pipeline(spark)
        return seq_df.select("block_id", "seq_deviation_score")


def _load_cluster_scores(spark: SparkSession) -> DataFrame:
    """Load BisectingKMeans cluster outlier scores."""
    try:
        df = spark.read.parquet(HDFS_CLUSTER_SCORES)
        logger.info("Cluster scores loaded from HDFS: {:,} rows", df.count())
        return df.select("block_id", "cluster_id", "cluster_outlier_score")
    except Exception:
        logger.warning("HDFS cluster scores not found. Running clustering now...")
        from mining.clustering import run_clustering_pipeline
        c_df = run_clustering_pipeline(spark)
        return c_df.select("block_id", "cluster_id", "cluster_outlier_score")


# ─── Load occurrence matrix ───────────────────────────────────────────────────

def _load_occurrence_features(spark: SparkSession) -> tuple[DataFrame, list[str]]:
    """
    Load Event_occurrence_matrix.csv and apply log1p normalization.

    log1p(x) = log(1 + x)
    Rationale: event counts are highly right-skewed — E5 appears 800k times,
    E9 appears ~3k times. log1p compresses the scale without losing zero values.
    (log1p(0) = 0, so zero-count events stay zero.)
    """
    df = spark.read.csv(
        str(DatasetConfig.OCCURRENCE_MATRIX_CSV),
        header=True,
        inferSchema=True,
    )

    block_col = next(c for c in df.columns if "block" in c.lower())
    event_cols = [
        c for c in df.columns
        if c != block_col
        and c.startswith("E")
        and c[1:].isdigit()
        and c not in ZERO_VARIANCE_EVENTS
    ]

    df = df.withColumnRenamed(block_col, "block_id")

    # log1p normalization on each event count column
    for col in event_cols:
        df = df.withColumn(
            f"{col}_norm",
            F.log1p(F.coalesce(F.col(col).cast("double"), F.lit(0.0))),
        )

    norm_cols = [f"{c}_norm" for c in event_cols]

    result = df.select(["block_id"] + norm_cols)

    logger.info(
        "Occurrence features loaded: {} events (log1p normalized), {:,} blocks",
        len(event_cols),
        result.count(),
    )

    return result, norm_cols


# ─── Derived block-level statistics ──────────────────────────────────────────

def _compute_block_stats(spark: SparkSession) -> DataFrame:
    """
    Compute per-block aggregate statistics from parsed HDFS logs.

    Reads from HDFS parsed_logs parquet (written by spark_streaming.py).
    Falls back to raw HDFS.log if parquet not available yet.

    Features computed:
        total_events       Total event count in block
        unique_event_count Number of distinct event IDs seen
        log_span_secs      Time from first to last log event (seconds)
                           proxy for how long a block operation took

    These 3 features capture temporal and volumetric anomaly signals
    that the occurrence matrix alone can't capture:
    - A block with 1000 events is unusual (normally ~7)
    - A block spanning 3600 seconds is unusual (normally <30s)
    """
    hdfs_parquet = f"hdfs://localhost:9000{HDFSConfig.PARSED_LOGS_PATH}"

    try:
        parsed_df = spark.read.parquet(hdfs_parquet)
        logger.info("Parsed logs loaded from HDFS parquet")
    except Exception:
        logger.warning(
            "Parsed parquet not found at {}. "
            "Block stats will use occurrence matrix fallback.",
            hdfs_parquet,
        )
        return None

    # Parse log_time "203518" → seconds since midnight (for span calculation)
    def _time_to_secs(t: str) -> int:
        if t is None or len(t) < 6:
            return 0
        try:
            h = int(t[0:2])
            m = int(t[2:4])
            s = int(t[4:6])
            return h * 3600 + m * 60 + s
        except Exception:
            return 0

    time_udf = F.udf(_time_to_secs, IntegerType())

    with_secs = parsed_df.withColumn(
        "event_secs",
        time_udf(F.col("log_time")),
    )

    block_stats = with_secs.groupBy("block_id").agg(
        F.count("*").alias("total_events"),
        F.countDistinct("event_id").alias("unique_event_count"),
        (F.max("event_secs") - F.min("event_secs")).alias("log_span_secs"),
    )

    # log1p normalize total_events and log_span_secs (also right-skewed)
    block_stats = (
        block_stats
        .withColumn("total_events_norm",
                    F.log1p(F.col("total_events").cast("double")))
        .withColumn("log_span_secs_norm",
                    F.log1p(F.col("log_span_secs").cast("double")))
        .select(
            "block_id",
            "total_events_norm",
            "unique_event_count",
            "log_span_secs_norm",
        )
    )

    logger.info(
        "Block stats computed: {:,} blocks",
        block_stats.count(),
    )
    return block_stats


# ─── Feature join ─────────────────────────────────────────────────────────────

def build_feature_matrix(spark: SparkSession) -> tuple[DataFrame, list[str]]:
    """
    Join all feature sources into a single per-block feature matrix.

    Join strategy: left join on block_id from occurrence matrix (anchor).
    Missing values in mining scores → filled with neutral defaults:
        fp_rarity_score       → 0.5 (uncertain, not clearly normal or anomalous)
        seq_deviation_score   → 0.5
        cluster_outlier_score → 0.5
        cluster_id            → -1  (unassigned)
        block stats           → 0.0

    Returns:
        (feature_df, feature_cols)
        feature_df:   DataFrame with block_id + all feature columns
        feature_cols: list of feature column names (used by IF model)
    """
    logger.info("=== Building Feature Matrix ===")
    start = time.perf_counter()

    # 1. Occurrence matrix (anchor — all blocks present here)
    occur_df, norm_event_cols = _load_occurrence_features(spark)

    # 2. Mining scores
    fp_df      = _load_fp_scores(spark)
    seq_df     = _load_seq_scores(spark)
    cluster_df = _load_cluster_scores(spark)

    # 3. Block stats (optional — skip gracefully if streaming hasn't run yet)
    stats_df = _compute_block_stats(spark)

    # 4. Join everything on block_id
    logger.info("Joining feature sources...")
    features = (
        occur_df
        .join(fp_df,      on="block_id", how="left")
        .join(seq_df,     on="block_id", how="left")
        .join(cluster_df, on="block_id", how="left")
    )

    if stats_df is not None:
        features = features.join(stats_df, on="block_id", how="left")

    # 5. Fill nulls with neutral defaults
    fill_defaults = {
        "fp_rarity_score":       0.5,
        "seq_deviation_score":   0.5,
        "cluster_outlier_score": 0.5,
        "cluster_id":            -1,
        "total_events_norm":     0.0,
        "unique_event_count":    0.0,
        "log_span_secs_norm":    0.0,
    }
    for col in norm_event_cols:
        fill_defaults[col] = 0.0

    features = features.fillna(fill_defaults)

    # 6. Cast cluster_id to double for Isolation Forest (needs all-numeric)
    features = features.withColumn(
        "cluster_id",
        F.col("cluster_id").cast("double"),
    )

    # 7. Define final feature column list
    base_feature_cols = [
        "fp_rarity_score",
        "seq_deviation_score",
        "cluster_outlier_score",
        "cluster_id",
    ]
    stats_cols = (
        ["total_events_norm", "unique_event_count", "log_span_secs_norm"]
        if stats_df is not None else []
    )
    all_feature_cols = base_feature_cols + stats_cols + norm_event_cols

    # 8. Drop any constant columns (zero variance → useless for IF)
    # ✅ FIXED — convert Row to plain Python dict first
    sample = features.select(all_feature_cols).describe()
    stats_rows = {row["summary"]: row for row in sample.collect()}

    stddev_spark_row = stats_rows.get("stddev")
    stddev_row = stddev_spark_row.asDict() if stddev_spark_row is not None else {}

    constant_cols = [
        col for col in all_feature_cols
        if stddev_row.get(col) in (None, "0.0", "0", 0.0, 0)
    ]
    if constant_cols:
        logger.warning(
            "Dropping {} constant-variance features: {}",
            len(constant_cols),
            constant_cols,
        )
        all_feature_cols = [c for c in all_feature_cols if c not in constant_cols]

    total_features = len(all_feature_cols)
    total_blocks = features.count()
    elapsed = time.perf_counter() - start

    logger.success(
        "Feature matrix built in {:.1f}s | {:,} blocks × {} features",
        elapsed,
        total_blocks,
        total_features,
    )
    logger.info("Feature columns: {}", all_feature_cols)

    return features.select(["block_id"] + all_feature_cols), all_feature_cols


# ─── Save feature matrix ──────────────────────────────────────────────────────

def save_feature_matrix(
    feature_df: DataFrame,
    feature_cols: list[str],
) -> None:
    """
    Save feature matrix to:
    - HDFS parquet (for IF training in anomaly/isolation_forest.py)
    - Local CSV (for inspection / offline sklearn backup)
    """
    logger.info("Saving feature matrix to HDFS and local...")

    # HDFS
    feature_df.write.mode("overwrite").parquet(HDFS_FEATURE_OUT)
    logger.info("Feature matrix saved to HDFS: {}", HDFS_FEATURE_OUT)

    # Local CSV
    LOCAL_FEATURE_CSV.parent.mkdir(parents=True, exist_ok=True)
    # ✅ FIXED — write only a sample locally, full data is on HDFS
    feature_df.limit(5000).toPandas().to_csv(LOCAL_FEATURE_CSV, index=False)
    logger.info("Feature matrix sample (5k) saved locally: {}", LOCAL_FEATURE_CSV)
    logger.info("Feature matrix saved locally: {}", LOCAL_FEATURE_CSV)

    # Save feature column list for reproducibility
    feature_list_path = LOCAL_FEATURE_CSV.parent / "feature_columns.txt"
    feature_list_path.write_text("\n".join(feature_cols))
    logger.success(
        "Feature matrix saved: {:,} rows × {} features",
        feature_df.count(),
        len(feature_cols),
    )


# ─── Main ─────────────────────────────────────────────────────────────────────

def run_feature_builder(spark: SparkSession | None = None) -> tuple[DataFrame, list[str]]:
    """Full feature building pipeline."""
    if spark is None:
        spark = _get_spark()

    feature_df, feature_cols = build_feature_matrix(spark)
    save_feature_matrix(feature_df, feature_cols)
    return feature_df, feature_cols


if __name__ == "__main__":
    run_feature_builder()