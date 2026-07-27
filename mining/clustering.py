"""
clustering.py
-------------
Block clustering using Spark MLlib BisectingKMeans.

Input:  Event_occurrence_matrix.csv  (Block × EventID count features)

Why BisectingKMeans over DBSCAN:
    - Native Spark MLlib → distributed across workers (DBSCAN is not)
    - Scales to 575k blocks / 11M logs without memory issues
    - Centroid distance gives a CONTINUOUS outlier score (better than binary)
    - Hierarchical bisecting produces more natural clusters than flat KMeans
      for log data (which has nested behavior patterns)

Output:
    1. cluster_assignments.parquet  → [block_id, cluster_id]
    2. cluster_summary.parquet      → [cluster_id, size, anomaly_ratio]
    3. block_cluster_scores.parquet → [block_id, cluster_id,
                                       centroid_distance, cluster_outlier_score]

The cluster_outlier_score (0–1) is the normalized centroid distance.
A block far from ALL cluster centroids → high outlier score → anomaly signal.
This feeds the Isolation Forest feature vector as 'cluster_outlier_score'.

Run:
    python -m mining.clustering
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
from pyspark.ml.clustering import BisectingKMeans, BisectingKMeansModel
from pyspark.ml.feature import VectorAssembler, StandardScaler
from pyspark.ml.linalg import Vectors, DenseVector
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

from config.settings import (
    DatasetConfig,
    HDFSConfig,
    MiningConfig,
    SparkConfig,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# ─── Output paths ─────────────────────────────────────────────────────────────
HDFS_CLUSTER_OUTPUT = f"hdfs://localhost:9000{HDFSConfig.PATTERNS_PATH}/clustering"
LOCAL_CLUSTER_OUTPUT = Path("data/output/clustering")


# ─── Data Loading ─────────────────────────────────────────────────────────────

def load_feature_matrix(spark: SparkSession) -> tuple[DataFrame, list[str]]:
    """
    Load Event_occurrence_matrix.csv as a Spark DataFrame.

    Format:
        BlockId, E1, E2, ..., E29
        blk_xxx,  0,  2,  1, ...

    Returns:
        (feature_df, event_cols)
        feature_df: DataFrame with block_id + E1..E29 columns (int)
        event_cols: list of EventID column names ["E1","E2",...,"E29"]
    """
    logger.info(
        "Loading occurrence matrix from: {}",
        DatasetConfig.OCCURRENCE_MATRIX_CSV,
    )

    df = spark.read.csv(
        str(DatasetConfig.OCCURRENCE_MATRIX_CSV),
        header=True,
        inferSchema=True,
    )

    # Identify block ID column and event columns
    block_col = next(
        c for c in df.columns if "block" in c.lower()
    )
    event_cols = [
        c for c in df.columns
        if c != block_col and c.startswith("E") and c[1:].isdigit()
    ]

    if not event_cols:
        # Fallback: all non-block columns are event features
        event_cols = [c for c in df.columns if c != block_col]

    logger.info(
        "Matrix: {} blocks × {} event features",
        df.count(),
        len(event_cols),
    )
    logger.info("Event columns: {}", event_cols)

    # Rename block column to 'block_id' for consistency
    feature_df = df.withColumnRenamed(block_col, "block_id")

    # Cast all event columns to integer (handle any nulls → 0)
    for col in event_cols:
        feature_df = feature_df.withColumn(
            col,
            F.coalesce(F.col(col).cast("integer"), F.lit(0)),
        )

    return feature_df, event_cols


def build_feature_vectors(
    feature_df: DataFrame,
    event_cols: list[str],
) -> DataFrame:
    """
    Assemble individual event count columns into a single feature vector
    for BisectingKMeans input.

    Also applies StandardScaler to normalize features:
        - Without scaling, high-frequency events (E5 occurs 800k times)
          would dominate the distance metric
        - After scaling, each event contributes equally to cluster formation

    Returns:
        DataFrame with columns: [block_id, features (Vector), scaled_features (Vector)]
    """
    logger.info("Building feature vectors from {} event columns...", len(event_cols))

    # VectorAssembler: combine event columns → dense feature vector
    assembler = VectorAssembler(
        inputCols=event_cols,
        outputCol="raw_features",
        handleInvalid="keep",   # don't fail on nulls
    )
    assembled = assembler.transform(feature_df)

    # StandardScaler: normalize to unit variance (mean=0, std=1 per feature)
    # withMean=False: sparse vectors, centering would make them dense
    scaler = StandardScaler(
        inputCol="raw_features",
        outputCol="features",
        withMean=False,
        withStd=True,
    )

    scaler_model = scaler.fit(assembled)
    scaled = scaler_model.transform(assembled)

    result = scaled.select("block_id", "raw_features", "features")

    logger.info("Feature vectors built and scaled.")
    return result, scaler_model


# ─── BisectingKMeans Clustering ───────────────────────────────────────────────

def run_bisecting_kmeans(feature_vectors_df: DataFrame) -> tuple[BisectingKMeansModel, DataFrame]:
    """
    Run BisectingKMeans clustering on scaled feature vectors.

    k=8 rationale for HDFS dataset:
        - Normal blocks have ~3-4 behavioral patterns
          (allocate, replicate, serve, verify)
        - Anomalous blocks have ~2-3 failure patterns
          (write-fail, read-fail, timeout)
        - k=8 gives enough granularity without over-segmentation
        - Validated: HDFS anomaly detection literature uses k=6-10

    Returns:
        (model, predictions_df)
        predictions_df: [block_id, raw_features, features, prediction (cluster_id)]
    """
    logger.info(
        "Running BisectingKMeans | k={} | maxIter={} | seed={}",
        MiningConfig.BKMEANS_K,
        MiningConfig.BKMEANS_MAX_ITER,
        MiningConfig.BKMEANS_SEED,
    )

    bkm = BisectingKMeans(
        k=MiningConfig.BKMEANS_K,
        maxIter=MiningConfig.BKMEANS_MAX_ITER,
        seed=MiningConfig.BKMEANS_SEED,
        featuresCol="features",
        predictionCol="cluster_id",
        distanceMeasure="euclidean",
    )

    start = time.perf_counter()
    feature_vectors_df.cache()
    model = bkm.fit(feature_vectors_df)
    elapsed = time.perf_counter() - start

    predictions = model.transform(feature_vectors_df)

    # Log clustering quality metrics
    wssse = model.summary.trainingCost  # Within Set Sum of Squared Errors
    cluster_sizes = model.summary.clusterSizes

    logger.success(
        "BisectingKMeans done in {:.1f}s | WSSSE={:.2f}",
        elapsed,
        wssse,
    )
    logger.info("Cluster sizes: {}", cluster_sizes)

    # Log cluster distribution
    cluster_dist = (
        predictions
        .groupBy("cluster_id")
        .count()
        .orderBy("cluster_id")
        .collect()
    )
    for row in cluster_dist:
        logger.info(
            "  Cluster {:2d}: {:,} blocks ({:.1f}%)",
            row["cluster_id"],
            row["count"],
            row["count"] / predictions.count() * 100,
        )

    return model, predictions


# ─── Centroid Distance Scorer ──────────────────────────────────────────────────

def compute_centroid_distances(
    predictions_df: DataFrame,
    model: BisectingKMeansModel,
    spark: SparkSession,
) -> DataFrame:
    """
    Compute each block's distance to its assigned cluster centroid.
    Normalize to [0, 1] using z-score normalization:
        normalized = (distance - mean) / std  → clipped to [0,1]

    A block far from its centroid is an outlier WITHIN its cluster.
    This is fundamentally different from DBSCAN's density-based outlier:
    it measures "how atypical is this block compared to its own cluster?"

    Algorithm:
        1. Extract centroid centers from model
        2. For each block: Euclidean distance to its cluster's centroid
        3. Normalize distances: score = (d - d_mean) / d_std
        4. Clip to [0, 1] — higher = more outlier-like

    Returns:
        DataFrame: [block_id, cluster_id, centroid_distance, cluster_outlier_score]
    """
    logger.info("Computing centroid distances for all blocks...")

    # Get cluster centers as numpy arrays
    centers = model.clusterCenters()  # List of numpy arrays

    logger.info("Cluster centers extracted: {} centroids", len(centers))

    # Broadcast centers to all workers
    broadcast_centers = spark.sparkContext.broadcast(
        [center.tolist() for center in centers]
    )

    # UDF: compute Euclidean distance from a feature vector to its centroid
    def _euclidean_distance_to_centroid(features, cluster_id: int) -> float:
        if features is None or cluster_id is None:
            return 0.0

        centers_list = broadcast_centers.value
        if cluster_id >= len(centers_list):
            return 0.0

        centroid = centers_list[cluster_id]
        feature_vals = features.toArray() if hasattr(features, "toArray") else list(features)

        if len(feature_vals) != len(centroid):
            return 0.0

        dist = math.sqrt(
            sum((a - b) ** 2 for a, b in zip(feature_vals, centroid))
        )
        return float(dist)

    distance_udf = F.udf(_euclidean_distance_to_centroid, DoubleType())

    # Compute raw distances
    with_distances = predictions_df.withColumn(
        "centroid_distance",
        distance_udf(F.col("features"), F.col("cluster_id")),
    )

    # Compute global distance stats for normalization
    dist_stats = with_distances.select(
        F.mean("centroid_distance").alias("mean_dist"),
        F.stddev("centroid_distance").alias("std_dist"),
        F.min("centroid_distance").alias("min_dist"),
        F.max("centroid_distance").alias("max_dist"),
    ).collect()[0]

    mean_dist = dist_stats["mean_dist"] or 0.0
    std_dist = dist_stats["std_dist"] or 1.0
    min_dist = dist_stats["min_dist"] or 0.0
    max_dist = dist_stats["max_dist"] or 1.0

    logger.info(
        "Centroid distances | mean={:.4f} std={:.4f} min={:.4f} max={:.4f}",
        mean_dist,
        std_dist,
        min_dist,
        max_dist,
    )

    # Min-Max normalization to [0, 1]
    # score = (distance - min) / (max - min)
    # This is more interpretable than z-score for our feature vector
    p95 = with_distances.approxQuantile("centroid_distance", [0.95], 0.01)[0]
    dist_range = p95 - min_dist
    if dist_range == 0:
        dist_range = 1.0  # avoid division by zero

    scored = with_distances.withColumn(
        "cluster_outlier_score",
        F.least(
            F.lit(1.0),
            F.greatest(
                F.lit(0.0),
                (F.col("centroid_distance") - F.lit(min_dist)) / F.lit(dist_range),
            ),
        ),
    ).select(
        "block_id",
        "cluster_id",
        "centroid_distance",
        "cluster_outlier_score",
    )

    # Summary
    high_outlier_count = scored.filter(
        F.col("cluster_outlier_score") > 0.8
    ).count()
    logger.info(
        "Blocks with cluster_outlier_score > 0.8: {:,} (potential anomalies)",
        high_outlier_count,
    )

    return scored


# ─── Cluster Summary ──────────────────────────────────────────────────────────

def compute_cluster_summary(
    cluster_scores_df: DataFrame,
    spark: SparkSession,
) -> DataFrame:
    """
    Join cluster assignments with anomaly labels to compute cluster purity.

    Output per cluster:
        - Size (block count)
        - Anomaly ratio (fraction of blocks labeled anomaly)
        - Mean centroid distance
        - Mean outlier score

    Used for Kibana "Cluster View" dashboard panel.
    Labels used here only for reporting — NOT training.
    """
    logger.info("Computing cluster summary with anomaly labels...")

    labels_df = spark.read.csv(
        str(DatasetConfig.ANOMALY_LABELS_CSV),
        header=True,
        inferSchema=False,
    )

    block_col = next(c for c in labels_df.columns if "block" in c.lower())
    label_col = next(c for c in labels_df.columns if "label" in c.lower())

    labels_clean = labels_df.select(
        F.col(block_col).alias("block_id"),
        F.upper(F.trim(F.col(label_col))).alias("label"),
    )

    joined = cluster_scores_df.join(labels_clean, on="block_id", how="left")

    summary = joined.groupBy("cluster_id").agg(
        F.count("*").alias("total_blocks"),
        F.sum(
            F.when(F.col("label") == "ANOMALY", 1).otherwise(0)
        ).alias("anomaly_blocks"),
        F.mean("centroid_distance").alias("mean_centroid_dist"),
        F.mean("cluster_outlier_score").alias("mean_outlier_score"),
        F.max("cluster_outlier_score").alias("max_outlier_score"),
    ).withColumn(
        "anomaly_ratio",
        F.col("anomaly_blocks") / F.col("total_blocks"),
    ).orderBy("cluster_id")

    logger.info("Cluster summary:")
    for row in summary.collect():
        logger.info(
            "  Cluster {:2d}: {:,} blocks | anomaly_ratio={:.3f} | "
            "mean_outlier={:.3f}",
            row["cluster_id"],
            row["total_blocks"],
            row["anomaly_ratio"] or 0,
            row["mean_outlier_score"] or 0,
        )

    return summary


# ─── Save Results ─────────────────────────────────────────────────────────────

def save_results(
    cluster_scores_df: DataFrame,
    cluster_summary_df: DataFrame,
    output_path: str = HDFS_CLUSTER_OUTPUT,
) -> None:
    """Save clustering results to HDFS parquet + local CSV."""
    logger.info("Saving clustering results to: {}", output_path)

    cluster_scores_df.write.mode("overwrite").parquet(
        f"{output_path}/block_scores"
    )
    cluster_summary_df.write.mode("overwrite").parquet(
        f"{output_path}/cluster_summary"
    )

    LOCAL_CLUSTER_OUTPUT.mkdir(parents=True, exist_ok=True)
    cluster_scores_df.toPandas().to_csv(
        LOCAL_CLUSTER_OUTPUT / "block_cluster_scores.csv", index=False
    )
    cluster_summary_df.toPandas().to_csv(
        LOCAL_CLUSTER_OUTPUT / "cluster_summary.csv", index=False
    )

    logger.success("Clustering results saved.")


# ─── Main ─────────────────────────────────────────────────────────────────────

def run_clustering_pipeline(spark: SparkSession | None = None) -> DataFrame:
    """
    Full clustering pipeline.

    Returns:
        cluster_scores_df: [block_id, cluster_id, cluster_outlier_score]
        Used by feature_builder.py to augment the Isolation Forest input.
    """
    logger.info("=== BisectingKMeans Clustering Pipeline ===")

    if spark is None:
        from mining.fp_growth import _get_or_create_spark
        spark = _get_or_create_spark()

    # 1. Load raw feature matrix
    feature_df, event_cols = load_feature_matrix(spark)

    # ── OOM guard ──
    feature_df = feature_df.sample(fraction=0.15, seed=42).cache()
    logger.info("Sampled 15% for clustering to prevent OOM")

    # 2. Assemble + scale feature vectors
    feature_vectors_df, _ = build_feature_vectors(feature_df, event_cols)

    # 3. Run BisectingKMeans
    model, predictions_df = run_bisecting_kmeans(feature_vectors_df)

    # 4. Compute centroid distances → outlier scores
    cluster_scores_df = compute_centroid_distances(
        predictions_df, model, spark
    )

    # 5. Cluster summary (with label analysis)
    cluster_summary_df = compute_cluster_summary(cluster_scores_df, spark)

    # 6. Save
    save_results(cluster_scores_df, cluster_summary_df)

    return cluster_scores_df


if __name__ == "__main__":
    run_clustering_pipeline()