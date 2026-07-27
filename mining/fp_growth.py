"""
fp_growth.py
------------
Frequent Pattern Mining on HDFS event data using Spark MLlib FPGrowth.

Input:  Event_occurrence_matrix.csv  (Block × EventID count matrix)
        OR Event_traces.csv          (Block → ordered event list)

Output:
    1. freq_itemsets.parquet   → {items: [E5, E22], freq: 82341}
    2. association_rules.parquet → {antecedent, consequent, confidence, lift}
    3. block_fp_scores.parquet   → per-block rarity score (0.0–1.0)
       score=0: block events are very common (normal)
       score=1: block events are very rare (anomaly signal)

The per-block rarity score feeds into the Isolation Forest feature vector
as one of the 32 features (fp_rare_score column).

Run:
    python -m mining.fp_growth
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
from pyspark.ml.fpm import FPGrowth
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    ArrayType,
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
HDFS_FP_OUTPUT = f"hdfs://localhost:9000{HDFSConfig.PATTERNS_PATH}/fp_growth"
LOCAL_FP_OUTPUT = Path("data/output/fp_growth")

# ─── Schema for event set DataFrame ──────────────────────────────────────────
EVENT_SET_SCHEMA = StructType([
    StructField("block_id", StringType(), False),
    StructField("events", ArrayType(StringType()), False),
])


# ─── Spark Session ────────────────────────────────────────────────────────────

def _get_or_create_spark() -> SparkSession:
    """Get existing SparkSession or create a minimal one for batch mining."""
    existing = SparkSession.getActiveSession()
    if existing:
        return existing

    return (
        SparkSession.builder
        .appName(f"{SparkConfig.APP_NAME}-FPGrowth")
        .master(SparkConfig.MASTER)
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.driver.memory", "4g")
        .config("spark.executor.memory", "4g")
        .getOrCreate()
    )


# ─── Data Loading ─────────────────────────────────────────────────────────────

def load_event_sets_from_traces(spark: SparkSession) -> DataFrame:
    logger.info("Loading event traces from: {}", DatasetConfig.EVENT_TRACES_CSV)

    traces_df = spark.read.csv(
        str(DatasetConfig.EVENT_TRACES_CSV),
        header=True,
        inferSchema=False,
    )

    # Parse [E5,E22,E5,...] → unique set ["E5", "E22", ...]
    event_sets = traces_df.select(
        F.col("BlockId").alias("block_id"),
        F.array_distinct(
            F.split(
                F.regexp_replace(F.col("Features"), r"[\[\]\s]", ""),
                ","
            )
        ).alias("events"),
    ).filter(
        F.col("block_id").isNotNull() &
        F.col("events").isNotNull() &
        (F.size(F.col("events")) > 0)
    )

    count = event_sets.count()
    logger.info("Loaded {:,} block event sets", count)
    return event_sets


def load_event_sets_from_matrix(spark: SparkSession) -> DataFrame:
    """
    Alternative: Load Event_occurrence_matrix.csv → event sets.

    Occurrence matrix format:
        BlockId, E1, E2, ..., E29
        blk_xxx,  0,  2,  1,  0 ...

    A block's event set = columns where count > 0.
    This gives slightly different results than traces — use traces as primary.
    """
    logger.info(
        "Loading event occurrence matrix from: {}",
        DatasetConfig.OCCURRENCE_MATRIX_CSV,
    )

    matrix_df = spark.read.csv(
        str(DatasetConfig.OCCURRENCE_MATRIX_CSV),
        header=True,
        inferSchema=True,
    )

    # Get EventID columns (all columns except BlockId)
    block_col = next(
        c for c in matrix_df.columns if "block" in c.lower()
    )
    event_cols = [c for c in matrix_df.columns if c != block_col]

    logger.info(
        "Matrix: {:,} blocks × {} event types",
        matrix_df.count(),
        len(event_cols),
    )

    # Convert matrix row → list of event IDs where count > 0
    # Build array of event IDs conditionally
    event_array_expr = F.array(
        *[
            F.when(F.col(c) > 0, F.lit(c)).otherwise(F.lit(None))
            for c in event_cols
        ]
    )

    event_sets = matrix_df.select(
        F.col(block_col).alias("block_id"),
        F.array_remove(event_array_expr, None).alias("events"),
    ).filter(F.size(F.col("events")) > 0)

    return event_sets


# ─── FP-Growth Mining ─────────────────────────────────────────────────────────

def run_fp_growth(event_sets_df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """
    Run FPGrowth on block event sets.

    Args:
        event_sets_df: DataFrame with columns [block_id, events: array<string>]

    Returns:
        (freq_itemsets_df, rules_df)
        freq_itemsets_df: {items: array<string>, freq: long}
        rules_df:         {antecedent, consequent, confidence, lift}
    """
    logger.info(
        "Running FP-Growth | minSupport={} | minConfidence={}",
        MiningConfig.FP_GROWTH_MIN_SUPPORT,
        MiningConfig.FP_GROWTH_MIN_CONFIDENCE,
    )

    fp_model = FPGrowth(
        itemsCol="events",
        minSupport=MiningConfig.FP_GROWTH_MIN_SUPPORT,
        minConfidence=MiningConfig.FP_GROWTH_MIN_CONFIDENCE,
    )

    start = time.perf_counter()

    # FPGrowth requires a persisted DataFrame for efficiency on large data
    event_sets_df.cache()

    model = fp_model.fit(event_sets_df)

    freq_itemsets = model.freqItemsets
    rules = model.associationRules

    elapsed = time.perf_counter() - start

    freq_count = freq_itemsets.count()
    rules_count = rules.count()

    logger.success(
        "FP-Growth complete in {:.1f}s | {:,} frequent itemsets | {:,} rules",
        elapsed,
        freq_count,
        rules_count,
    )

    # Log top 10 most frequent itemsets
    logger.info("Top 10 most frequent itemsets:")
    top_patterns = (
        freq_itemsets
        .orderBy(F.col("freq").desc())
        .limit(10)
        .collect()
    )
    for row in top_patterns:
        logger.info(
            "  {} → freq={:,}",
            sorted(row["items"]),
            row["freq"],
        )

    return freq_itemsets, rules


# ─── Per-block Rarity Score ───────────────────────────────────────────────────

def compute_block_rarity_scores(
    event_sets_df: DataFrame,
    freq_itemsets_df: DataFrame,
) -> DataFrame:
    """
    Compute a rarity score (0.0–1.0) per block based on FP-Growth results.

    Algorithm:
        For each block, find the maximum support among all its sub-itemsets
        that appear in freq_itemsets.
        rarity_score = 1 - max_support

        Intuition:
            - Normal blocks: their event combos have HIGH support → low rarity
            - Anomalous blocks: event combos are RARE → high rarity score

        Blocks with events not found in any frequent itemset get score = 1.0
        (maximally anomalous from FP perspective).

    Returns:
        DataFrame: [block_id, max_support, fp_rarity_score]
    """
    logger.info("Computing per-block FP rarity scores...")

    total_blocks = event_sets_df.count()
    logger.info("Total blocks: {:,}", total_blocks)

    # Normalize freq to support (0–1 range)
    # support = freq / total_blocks
    freq_with_support = freq_itemsets_df.withColumn(
        "support",
        F.col("freq") / F.lit(float(total_blocks)),
    )

    # Build a lookup: itemset_str → support
    # We represent each itemset as a sorted comma-joined string for joining
    freq_with_key = freq_with_support.withColumn(
        "items_key",
        F.array_join(F.sort_array(F.col("items")), ","),
    ).select("items_key", "support")

    # For each block, generate all sub-itemsets of size >= 1
    # Then join with freq_itemsets to find the highest-support sub-itemset
    # NOTE: For large blocks (many events), this could be large.
    # We limit to single-item and pair-item lookups for scalability.

    # Single-item support lookup
    single_items = freq_with_support.filter(
        F.size(F.col("items")) == 1
    ).select(
        F.col("items").getItem(0).alias("event_id"),
        F.col("support").alias("single_support"),
    )

    # Explode block events → join with single-item support → max per block
    block_max_single = (
        event_sets_df
        .select(
            F.col("block_id"),
            F.explode(F.col("events")).alias("event_id"),
        )
        .join(single_items, on="event_id", how="left")
        .groupBy("block_id")
        .agg(
            F.max("single_support").alias("max_single_support"),
            F.min("single_support").alias("min_single_support"),
            F.avg("single_support").alias("avg_single_support"),
        )
    )

    # Pair-item support lookup
    pair_items = freq_with_support.filter(
        F.size(F.col("items")) == 2
    ).withColumn(
        "items_key",
        F.array_join(F.sort_array(F.col("items")), ","),
    ).select("items_key", F.col("support").alias("pair_support"))

    # Rarity score based on individual event supports
    # score = 1 - avg_single_support  (normalized 0-1)
    # We use avg rather than max to be sensitive to multiple rare events
    block_scores = block_max_single.withColumn(
        "fp_rarity_score",
        F.greatest(
            F.lit(0.0),
            F.least(
                F.lit(1.0),
                F.lit(1.0) - F.col("avg_single_support"),
            ),
        ),
    ).select(
        "block_id",
        F.col("max_single_support"),
        F.col("avg_single_support"),
        F.col("fp_rarity_score"),
    )

    # Blocks with NO matching events in freq_itemsets → score = 1.0
    all_blocks = event_sets_df.select("block_id")
    block_scores_complete = (
        all_blocks
        .join(block_scores, on="block_id", how="left")
        .fillna({"fp_rarity_score": 1.0, "max_single_support": 0.0})
    )

    scored_count = block_scores_complete.filter(
        F.col("fp_rarity_score") > 0
    ).count()
    logger.info(
        "FP rarity scores computed: {:,} blocks with score > 0",
        scored_count,
    )

    return block_scores_complete


# ─── Save Results ─────────────────────────────────────────────────────────────

def save_results(
    freq_itemsets_df: DataFrame,
    rules_df: DataFrame,
    block_scores_df: DataFrame,
    output_path: str = HDFS_FP_OUTPUT,
) -> None:
    """
    Save FP-Growth results to HDFS as parquet.
    Also saves a local copy for inspection.
    """
    logger.info("Saving FP-Growth results to: {}", output_path)

    # HDFS
    freq_itemsets_df.write.mode("overwrite").parquet(
        f"{output_path}/freq_itemsets"
    )
    rules_df.write.mode("overwrite").parquet(f"{output_path}/rules")
    block_scores_df.write.mode("overwrite").parquet(
        f"{output_path}/block_scores"
    )

    # Local copies for inspection
    LOCAL_FP_OUTPUT.mkdir(parents=True, exist_ok=True)

    freq_itemsets_df.limit(1000).toPandas().to_csv(
        LOCAL_FP_OUTPUT / "freq_itemsets_sample.csv", index=False
    )
    rules_df.limit(500).toPandas().to_csv(
        LOCAL_FP_OUTPUT / "rules_sample.csv", index=False
    )
    block_scores_df.toPandas().to_csv(
        LOCAL_FP_OUTPUT / "block_scores.csv", index=False
    )

    logger.success("FP-Growth results saved.")


# ─── Main ─────────────────────────────────────────────────────────────────────

def run_fp_growth_pipeline(spark: SparkSession | None = None) -> DataFrame:
    """
    Full FP-Growth pipeline.

    Returns:
        block_scores_df: [block_id, fp_rarity_score] — used by feature_builder.py
    """
    logger.info("=== FP-Growth Mining Pipeline ===")

    if spark is None:
        spark = _get_or_create_spark()

    # Load data — prefer Event_traces.csv (richer)
    if DatasetConfig.EVENT_TRACES_CSV.exists():
        event_sets_df = load_event_sets_from_traces(spark)
    else:
        logger.warning(
            "Event_traces.csv not found, falling back to occurrence matrix"
        )
        event_sets_df = load_event_sets_from_matrix(spark)

    # ── OOM guard ──
    event_sets_df = event_sets_df.sample(fraction=0.2, seed=42).cache()
    logger.info("Sampled 20% for FP-Growth to prevent OOM")

    # Run FP-Growth
    freq_itemsets_df, rules_df = run_fp_growth(event_sets_df)

    # Compute per-block rarity scores
    block_scores_df = compute_block_rarity_scores(
        event_sets_df, freq_itemsets_df
    )

    # Save
    save_results(freq_itemsets_df, rules_df, block_scores_df)

    return block_scores_df


if __name__ == "__main__":
    run_fp_growth_pipeline()