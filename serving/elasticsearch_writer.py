"""
serving/elasticsearch_writer.py
--------------------------------
Centralised Elasticsearch write layer for LogSense AI.

Used by:
    processing/spark_streaming.py  → write parsed logs per micro-batch
    batch/batch_job.py             → write anomaly scores hourly
    evaluation/metrics.py          → write evaluation metrics
    api/main.py                    → read-back via ES client

Responsibilities:
    1. Bootstrap ES indices with correct mappings (run once on startup)
    2. Bulk-write structured parsed logs  → index: logsense-logs
    3. Bulk-write anomaly results         → index: logsense-anomalies
    4. Write evaluation metrics snapshot  → index: logsense-metrics
    5. Write pattern mining results       → index: logsense-patterns
    6. Write cluster summary              → index: logsense-clusters

Design:
    - All writes go through ElasticsearchWriter class
    - Singleton pattern — one ES client reused across all writes
    - Bulk API used everywhere (never single-doc index calls in loops)
    - Retry with exponential backoff on transient failures
    - Upsert (index + doc_as_upsert) so re-runs are idempotent
    - Dead-letter queue: failed docs written to local JSONL for replay

Install:
    pip install elasticsearch>=8.13.0

Usage:
    from serving.elasticsearch_writer import get_writer

    writer = get_writer()
    writer.write_parsed_logs(batch_df)            # Spark DataFrame
    writer.write_anomaly_scores(scored_df)        # pandas DataFrame
    writer.write_metrics(metrics_dict)            # evaluation results
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from elasticsearch import Elasticsearch, helpers, ConnectionError, TransportError
from elasticsearch.helpers import BulkIndexError

from config.settings import ESConfig
from utils.logger import get_logger

logger = get_logger(__name__)

# ─── Dead-letter queue path ───────────────────────────────────────────────────
DLQ_PATH = Path("data/output/es_dead_letter.jsonl")

# ─── Retry config ─────────────────────────────────────────────────────────────
MAX_RETRIES    = 3
RETRY_BACKOFF  = 2.0   # seconds, doubled each retry


# ─── Index Mappings ───────────────────────────────────────────────────────────

# logsense-logs: one doc per parsed log line
LOGS_MAPPING = {
    "mappings": {
        "properties": {
            "block_id":     {"type": "keyword"},
            "event_id":     {"type": "keyword"},
            "log_date":     {"type": "keyword"},
            "log_time":     {"type": "keyword"},
            "pid":          {"type": "keyword"},
            "level":        {"type": "keyword"},
            "component":    {"type": "keyword"},
            "content":      {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "is_high_risk": {"type": "boolean"},
            "ingested_at":  {"type": "date"},
            "processed_at": {"type": "date"},
            "line_no":      {"type": "long"},
        }
    },
    "settings": {
        "number_of_shards":   1,
        "number_of_replicas": 0,         # 0 replicas for single-node dev
        "refresh_interval":  "5s",       # reduce refresh overhead
    },
}

# logsense-anomalies: one doc per anomalous block
ANOMALIES_MAPPING = {
    "mappings": {
        "properties": {
            "block_id":          {"type": "keyword"},
            "if_score":          {"type": "float"},
            "is_anomaly":        {"type": "integer"},
            "threshold":         {"type": "float"},
            "threshold_method":  {"type": "keyword"},
            "fp_rarity_score":   {"type": "float"},
            "seq_deviation_score": {"type": "float"},
            "cluster_outlier_score": {"type": "float"},
            "cluster_id":        {"type": "integer"},
            "detected_at":       {"type": "date"},
            "source":            {"type": "keyword"},   # "batch_layer" | "streaming_prescreening"
            "confirmed":         {"type": "boolean"},   # True = batch confirmed
        }
    },
    "settings": {
        "number_of_shards":   1,
        "number_of_replicas": 0,
    },
}

# logsense-metrics: evaluation run snapshots
METRICS_MAPPING = {
    "mappings": {
        "properties": {
            "run_id":      {"type": "keyword"},
            "run_at":      {"type": "date"},
            "precision":   {"type": "float"},
            "recall":      {"type": "float"},
            "f1_score":    {"type": "float"},
            "f05_score":   {"type": "float"},
            "f2_score":    {"type": "float"},
            "mcc":         {"type": "float"},
            "auc_roc":     {"type": "float"},
            "auc_pr":      {"type": "float"},
            "true_positives":  {"type": "integer"},
            "false_positives": {"type": "integer"},
            "true_negatives":  {"type": "integer"},
            "false_negatives": {"type": "integer"},
            "total_blocks":    {"type": "integer"},
            "anomaly_rate_true": {"type": "float"},
            "anomaly_rate_pred": {"type": "float"},
            "threshold":         {"type": "float"},
            "threshold_method":  {"type": "keyword"},
        }
    },
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
}

# logsense-patterns: FP-Growth + PrefixSpan results
PATTERNS_MAPPING = {
    "mappings": {
        "properties": {
            "pattern_id":    {"type": "keyword"},
            "pattern_type":  {"type": "keyword"},   # "itemset" | "sequence"
            "items":         {"type": "keyword"},    # array of EventIDs
            "freq":          {"type": "long"},
            "support":       {"type": "float"},
            "confidence":    {"type": "float"},
            "lift":          {"type": "float"},
            "computed_at":   {"type": "date"},
        }
    },
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
}

# logsense-clusters: BisectingKMeans cluster summaries
CLUSTERS_MAPPING = {
    "mappings": {
        "properties": {
            "cluster_id":         {"type": "integer"},
            "total_blocks":       {"type": "long"},
            "anomaly_blocks":     {"type": "long"},
            "anomaly_ratio":      {"type": "float"},
            "mean_centroid_dist": {"type": "float"},
            "mean_outlier_score": {"type": "float"},
            "max_outlier_score":  {"type": "float"},
            "computed_at":        {"type": "date"},
        }
    },
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
}

# Index → mapping registry
INDEX_REGISTRY: dict[str, dict] = {
    ESConfig.INDEX_LOGS:       LOGS_MAPPING,
    ESConfig.INDEX_ANOMALIES:  ANOMALIES_MAPPING,
    ESConfig.INDEX_METRICS:    METRICS_MAPPING,
    "logsense-patterns":       PATTERNS_MAPPING,
    "logsense-clusters":       CLUSTERS_MAPPING,
}


# ─── Writer class ─────────────────────────────────────────────────────────────

class ElasticsearchWriter:
    """
    Thread-safe, reusable Elasticsearch writer for LogSense AI.

    All public methods:
        bootstrap_indices()             Create indices with mappings if not exist
        write_parsed_logs(df)           Spark or pandas DataFrame → logsense-logs
        write_anomaly_scores(df)        pandas DataFrame → logsense-anomalies
        write_metrics(metrics_dict)     dict → logsense-metrics
        write_patterns(df, ptype)       pandas DataFrame → logsense-patterns
        write_clusters(df)              pandas DataFrame → logsense-clusters
        health()                        Returns dict of index health stats
    """

    def __init__(self):
        self._client: Elasticsearch | None = None
        self._bootstrapped: bool = False

    # ── ES client ─────────────────────────────────────────────────────────────

    @property
    def client(self) -> Elasticsearch:
        """Lazy-init ES client. Reused across all calls."""
        if self._client is None:
            logger.info("Connecting to Elasticsearch: {}", ESConfig.url())
            self._client = Elasticsearch(
                ESConfig.url(),
                http_auth=(ESConfig.USERNAME, ESConfig.PASSWORD)
                if ESConfig.PASSWORD else None,
                # Connection pool
                maxsize=10,
                # Timeouts
                request_timeout=30,
                retry_on_timeout=True,
                max_retries=3,
                # Sniff disabled — single-node dev setup
                sniff_on_start=False,
            )
            # Verify
            if not self._client.ping():
                raise ConnectionError(
                    f"Cannot connect to Elasticsearch at {ESConfig.url()}. "
                    "Is ES running? Check docker-compose."
                )
            logger.success("Elasticsearch connected: {}", ESConfig.url())
        return self._client

    # ── Index bootstrap ───────────────────────────────────────────────────────

    def bootstrap_indices(self) -> None:
        """
        Create all LogSense indices with correct mappings if they don't exist.
        Safe to call multiple times — skips existing indices.
        Called once on startup by api/main.py and batch_job.py.
        """
        if self._bootstrapped:
            return

        logger.info("Bootstrapping Elasticsearch indices...")

        for index_name, mapping in INDEX_REGISTRY.items():
            try:
                if not self.client.indices.exists(index=index_name):
                    self.client.indices.create(index=index_name, body=mapping)
                    logger.info("Created index: {}", index_name)
                else:
                    logger.debug("Index already exists: {}", index_name)
            except Exception as exc:
                logger.error("Failed to create index {}: {}", index_name, exc)
                raise

        self._bootstrapped = True
        logger.success(
            "ES indices ready: {}",
            list(INDEX_REGISTRY.keys()),
        )

    # ── Core bulk write ───────────────────────────────────────────────────────

    def _bulk_write(
        self,
        docs: list[dict],
        index: str,
        id_field: str | None = None,
        chunk_size: int = 500,
    ) -> tuple[int, int]:
        """
        Bulk write documents to an ES index with retry + dead-letter queue.

        Args:
            docs:       List of source dicts (not ES action format)
            index:      Target ES index name
            id_field:   Field to use as document _id (None = ES auto-ID)
            chunk_size: Docs per bulk request (default 500)

        Returns:
            (success_count, failed_count)
        """
        if not docs:
            return 0, 0

        # Build ES bulk actions
        actions = []
        for doc in docs:
            action = {
                "_index":  index,
                "_source": doc,
                "_op_type": "index",
            }
            if id_field and id_field in doc:
                action["_id"] = str(doc[id_field])
            actions.append(action)

        success = 0
        failed  = 0

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                ok, errors = helpers.bulk(
                    self.client,
                    actions,
                    chunk_size=chunk_size,
                    raise_on_error=False,
                    raise_on_exception=False,
                    stats_only=False,
                )
                success = ok
                if errors:
                    failed = len(errors)
                    logger.warning(
                        "Bulk write partial failure: {}/{} docs failed (index={})",
                        failed,
                        len(docs),
                        index,
                    )
                    self._write_dead_letter(errors, index)
                break   # Success (even partial) — don't retry

            except (ConnectionError, TransportError) as exc:
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF * (2 ** (attempt - 1))
                    logger.warning(
                        "ES bulk write attempt {}/{} failed: {}. "
                        "Retrying in {:.1f}s...",
                        attempt,
                        MAX_RETRIES,
                        exc,
                        wait,
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        "ES bulk write failed after {} attempts: {}. "
                        "Writing {:,} docs to dead-letter queue.",
                        MAX_RETRIES,
                        exc,
                        len(docs),
                    )
                    self._write_dead_letter(docs, index)
                    failed = len(docs)

            except Exception as exc:
                logger.error(
                    "Unexpected ES write error (index={}): {}",
                    index,
                    exc,
                )
                self._write_dead_letter(docs, index)
                failed = len(docs)
                break

        return success, failed

    # ── Dead-letter queue ─────────────────────────────────────────────────────

    @staticmethod
    def _write_dead_letter(failed_docs: list, index: str) -> None:
        """
        Append failed documents to a local JSONL file for manual replay.
        Each line: {"index": "...", "doc": {...}}
        """
        DLQ_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DLQ_PATH, "a") as f:
            for doc in failed_docs:
                entry = {
                    "index": index,
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                    "doc": doc if isinstance(doc, dict) else str(doc),
                }
                f.write(json.dumps(entry) + "\n")
        logger.info(
            "Dead-letter: {} docs written to {}",
            len(failed_docs),
            DLQ_PATH,
        )

    # ── Write: parsed logs ────────────────────────────────────────────────────

    def write_parsed_logs(
        self,
        df,
        batch_id: int | None = None,
    ) -> tuple[int, int]:
        """
        Write structured parsed log records to 'logsense-logs' index.

        Accepts both:
            - Spark DataFrame  (called from spark_streaming.py foreachBatch)
            - pandas DataFrame (called from batch_job.py or tests)

        Each doc is UPSERTED by line_no as _id to prevent duplicates
        on streaming restart.

        Args:
            df:       Spark or pandas DataFrame with parsed log schema
            batch_id: Spark micro-batch ID (for logging only)

        Returns:
            (success, failed)
        """
        self.bootstrap_indices()

        # Convert Spark DF → pandas if needed
        if hasattr(df, "toPandas"):
            pdf = df.toPandas()
        else:
            pdf = df

        if pdf.empty:
            logger.debug(
                "write_parsed_logs: empty batch {} — skipping",
                batch_id,
            )
            return 0, 0

        count = len(pdf)
        logger.info(
            "Writing {:,} parsed log records to ES (batch_id={})",
            count,
            batch_id,
        )

        # Build docs — keep only columns that exist in mapping
        expected_cols = {
            "block_id", "event_id", "log_date", "log_time",
            "pid", "level", "component", "content",
            "is_high_risk", "ingested_at", "processed_at", "line_no",
        }
        available = expected_cols & set(pdf.columns)

        docs = []
        for _, row in pdf[list(available)].iterrows():
            doc = row.to_dict()
            # Convert NaN → None for clean JSON
            doc = {
                k: (None if (isinstance(v, float) and v != v) else v)
                for k, v in doc.items()
            }
            # Convert pandas Timestamp → ISO string
            for ts_col in ("ingested_at", "processed_at"):
                if ts_col in doc and doc[ts_col] is not None:
                    try:
                        doc[ts_col] = str(doc[ts_col])
                    except Exception:
                        pass
            docs.append(doc)

        success, failed = self._bulk_write(
            docs,
            index=ESConfig.INDEX_LOGS,
            id_field="line_no",
            chunk_size=1000,
        )

        logger.info(
            "Parsed logs written → ES | success={:,} failed={:,}",
            success,
            failed,
        )
        return success, failed

    # ── Write: anomaly scores ─────────────────────────────────────────────────

    def write_anomaly_scores(
        self,
        scored_df: pd.DataFrame,
        source: str = "batch_layer",
        only_anomalies: bool = False,
    ) -> tuple[int, int]:
        """
        Write anomaly scoring results to 'logsense-anomalies' index.

        Args:
            scored_df:     pandas DataFrame with columns:
                           [block_id, if_score, is_anomaly, threshold, ...]
            source:        "batch_layer" | "streaming_prescreening"
            only_anomalies: If True, write only is_anomaly==1 blocks.
                            Set False to write all scores for dashboard
                            score-distribution visualization.

        Returns:
            (success, failed)
        """
        self.bootstrap_indices()

        if scored_df.empty:
            return 0, 0

        df = scored_df.copy()

        if only_anomalies:
            df = df[df["is_anomaly"] == 1]
            if df.empty:
                logger.info("No anomalies to write to ES.")
                return 0, 0

        run_ts = datetime.now(timezone.utc).isoformat()
        docs   = []

        for _, row in df.iterrows():
            doc: dict[str, Any] = {
                "block_id":   str(row["block_id"]),
                "if_score":   float(row.get("if_score",   0.0)),
                "is_anomaly": int(row.get("is_anomaly",   0)),
                "threshold":  float(row.get("threshold",  0.0)),
                "threshold_method": str(row.get("threshold_method", "")),
                "source":     source,
                "confirmed":  source == "batch_layer",
                "detected_at": run_ts,
            }

            # Optional mining score columns (present if feature matrix joined)
            for opt_col in (
                "fp_rarity_score",
                "seq_deviation_score",
                "cluster_outlier_score",
                "cluster_id",
            ):
                if opt_col in row.index and row[opt_col] is not None:
                    val = row[opt_col]
                    if isinstance(val, float) and val != val:  # NaN check
                        continue
                    doc[opt_col] = float(val) if opt_col != "cluster_id" else int(val)

            docs.append(doc)

        logger.info(
            "Writing {:,} anomaly records to ES (source={})",
            len(docs),
            source,
        )

        success, failed = self._bulk_write(
            docs,
            index=ESConfig.INDEX_ANOMALIES,
            id_field="block_id",    # upsert by block_id — idempotent
        )

        logger.success(
            "Anomaly scores written → ES | success={:,} failed={:,} | "
            "anomalies={:,} / {:,}",
            success,
            failed,
            int(df["is_anomaly"].sum()),
            len(df),
        )
        return success, failed

    # ── Write: evaluation metrics ─────────────────────────────────────────────

    def write_metrics(self, metrics: dict) -> bool:
        """
        Write a single evaluation metrics snapshot to 'logsense-metrics'.

        Called by evaluation/metrics.py after each evaluation run.
        Each run gets a unique run_id (timestamp-based) so history is preserved.

        Args:
            metrics: dict from compute_core_metrics() + threshold info

        Returns:
            True on success, False on failure
        """
        self.bootstrap_indices()

        run_at = datetime.now(timezone.utc)
        run_id = run_at.strftime("%Y%m%d_%H%M%S")

        # Flatten nested dict if needed (core_metrics is nested in full results)
        if "core_metrics" in metrics:
            flat = metrics["core_metrics"].copy()
            flat["threshold"]        = metrics.get("pot_threshold", 0.0)
            flat["threshold_method"] = "POT"
        else:
            flat = metrics.copy()

        flat["run_id"] = run_id
        flat["run_at"] = run_at.isoformat()

        success, failed = self._bulk_write(
            [flat],
            index=ESConfig.INDEX_METRICS,
            id_field="run_id",
        )

        if success:
            logger.success(
                "Metrics written → ES | run_id={} | F1={:.4f} P={:.4f} R={:.4f}",
                run_id,
                flat.get("f1_score", 0),
                flat.get("precision", 0),
                flat.get("recall", 0),
            )
            return True
        else:
            logger.error("Failed to write metrics to ES (run_id={})", run_id)
            return False

    # ── Write: frequent patterns ──────────────────────────────────────────────

    def write_patterns(
        self,
        patterns_df: pd.DataFrame,
        pattern_type: str = "itemset",
        total_blocks: int = 575_061,
    ) -> tuple[int, int]:
        """
        Write FP-Growth or PrefixSpan patterns to 'logsense-patterns'.

        Args:
            patterns_df:  pandas DataFrame with columns [items/sequence, freq]
                          items: list of EventIDs (FP-Growth)
                          sequence: nested list [[E5],[E22]] (PrefixSpan)
            pattern_type: "itemset" (FP-Growth) | "sequence" (PrefixSpan)
            total_blocks: Denominator for support calculation

        Returns:
            (success, failed)
        """
        self.bootstrap_indices()

        if patterns_df.empty:
            return 0, 0

        computed_at = datetime.now(timezone.utc).isoformat()
        docs = []

        for idx, row in patterns_df.iterrows():
            freq = int(row.get("freq", 0))
            support = round(freq / total_blocks, 6) if total_blocks > 0 else 0.0

            if pattern_type == "itemset":
                # FP-Growth: items is list of strings
                raw_items = row.get("items", [])
                items = list(raw_items) if not isinstance(raw_items, list) else raw_items
                pattern_key = "|".join(sorted(str(i) for i in items))
                doc = {
                    "pattern_id":   f"fp_{pattern_key}",
                    "pattern_type": "itemset",
                    "items":        items,
                    "freq":         freq,
                    "support":      support,
                    "confidence":   float(row.get("confidence", 0.0)),
                    "lift":         float(row.get("lift",       0.0)),
                    "computed_at":  computed_at,
                }
            else:
                # PrefixSpan: sequence is nested [[E5],[E22]]
                raw_seq = row.get("sequence", [])
                flat_events = [
                    item[0] for item in raw_seq
                    if isinstance(item, (list, tuple)) and item
                ]
                pattern_key = "→".join(flat_events)
                doc = {
                    "pattern_id":   f"seq_{idx}_{pattern_key[:50]}",
                    "pattern_type": "sequence",
                    "items":        flat_events,    # flattened for ES keyword array
                    "freq":         freq,
                    "support":      support,
                    "confidence":   0.0,
                    "lift":         0.0,
                    "computed_at":  computed_at,
                }

            docs.append(doc)

        logger.info(
            "Writing {:,} {} patterns to ES...",
            len(docs),
            pattern_type,
        )

        success, failed = self._bulk_write(
            docs,
            index="logsense-patterns",
            id_field="pattern_id",
            chunk_size=500,
        )

        logger.success(
            "Patterns written → ES | type={} success={:,} failed={:,}",
            pattern_type,
            success,
            failed,
        )
        return success, failed

    # ── Write: cluster summary ────────────────────────────────────────────────

    def write_clusters(self, cluster_summary_df: pd.DataFrame) -> tuple[int, int]:
        """
        Write BisectingKMeans cluster summary to 'logsense-clusters'.

        Args:
            cluster_summary_df: pandas DataFrame from clustering.py
                                 [cluster_id, total_blocks, anomaly_blocks,
                                  anomaly_ratio, mean_centroid_dist,
                                  mean_outlier_score, max_outlier_score]

        Returns:
            (success, failed)
        """
        self.bootstrap_indices()

        if cluster_summary_df.empty:
            return 0, 0

        computed_at = datetime.now(timezone.utc).isoformat()
        docs = []

        for _, row in cluster_summary_df.iterrows():
            doc = {
                "cluster_id":         int(row.get("cluster_id", -1)),
                "total_blocks":       int(row.get("total_blocks", 0)),
                "anomaly_blocks":     int(row.get("anomaly_blocks", 0)),
                "anomaly_ratio":      float(row.get("anomaly_ratio", 0.0) or 0.0),
                "mean_centroid_dist": float(row.get("mean_centroid_dist", 0.0) or 0.0),
                "mean_outlier_score": float(row.get("mean_outlier_score", 0.0) or 0.0),
                "max_outlier_score":  float(row.get("max_outlier_score", 0.0) or 0.0),
                "computed_at":        computed_at,
            }
            docs.append(doc)

        logger.info("Writing {} cluster summaries to ES...", len(docs))

        success, failed = self._bulk_write(
            docs,
            index="logsense-clusters",
            id_field="cluster_id",
        )

        logger.success(
            "Clusters written → ES | success={} failed={}",
            success,
            failed,
        )
        return success, failed

    # ── Dead-letter replay ────────────────────────────────────────────────────

    def replay_dead_letter(self) -> None:
        """
        Re-attempt writing docs from the dead-letter queue.
        Call manually or at startup if DLQ_PATH exists.
        """
        if not DLQ_PATH.exists():
            logger.info("No dead-letter queue found. Nothing to replay.")
            return

        lines = DLQ_PATH.read_text().strip().split("\n")
        records = [json.loads(l) for l in lines if l.strip()]

        if not records:
            return

        logger.warning(
            "Replaying {:,} docs from dead-letter queue: {}",
            len(records),
            DLQ_PATH,
        )

        by_index: dict[str, list[dict]] = {}
        for r in records:
            idx = r.get("index", ESConfig.INDEX_LOGS)
            by_index.setdefault(idx, []).append(r.get("doc", {}))

        total_success = 0
        for index, docs in by_index.items():
            ok, _ = self._bulk_write(docs, index=index)
            total_success += ok

        if total_success == len(records):
            DLQ_PATH.unlink()   # Delete DLQ if all replayed successfully
            logger.success(
                "Dead-letter replay complete — {:,} docs recovered.",
                total_success,
            )
        else:
            logger.warning(
                "Partial replay: {}/{} docs recovered. "
                "Dead-letter queue retained.",
                total_success,
                len(records),
            )

    # ── Health check ──────────────────────────────────────────────────────────

    def health(self) -> dict:
        """
        Return health status of all LogSense ES indices.
        Used by api/main.py /health endpoint.
        """
        status = {}
        try:
            for index in INDEX_REGISTRY:
                try:
                    info = self.client.cat.indices(
                        index=index,
                        format="json",
                        h="index,health,status,docs.count,store.size",
                    )
                    if info:
                        row = info[0]
                        status[index] = {
                            "health":     row.get("health",      "unknown"),
                            "status":     row.get("status",      "unknown"),
                            "doc_count":  row.get("docs.count",  "0"),
                            "store_size": row.get("store.size",  "0b"),
                        }
                    else:
                        status[index] = {"health": "missing"}
                except Exception:
                    status[index] = {"health": "error"}

        except Exception as exc:
            return {"error": str(exc)}

        return status


# ─── Module-level singleton ───────────────────────────────────────────────────

_writer: ElasticsearchWriter | None = None


def get_writer() -> ElasticsearchWriter:
    """
    Return the module-level singleton ElasticsearchWriter.
    Thread-safe (Python GIL protects singleton init).

    Usage:
        from serving.elasticsearch_writer import get_writer
        writer = get_writer()
        writer.write_anomaly_scores(df)
    """
    global _writer
    if _writer is None:
        _writer = ElasticsearchWriter()
    return _writer


# ─── __init__.py helper ───────────────────────────────────────────────────────
# serving/__init__.py should contain:
#   from serving.elasticsearch_writer import get_writer, ElasticsearchWriter
#   __all__ = ["get_writer", "ElasticsearchWriter"]


# ─── CLI for manual ops ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LogSense ES Writer CLI")
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Create all indices with mappings",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Print health of all LogSense indices",
    )
    parser.add_argument(
        "--replay-dlq",
        action="store_true",
        help="Replay failed docs from dead-letter queue",
    )
    parser.add_argument(
        "--write-scores",
        type=str,
        default=None,
        metavar="CSV_PATH",
        help="Bulk-write anomaly scores from a CSV file",
    )
    args = parser.parse_args()

    writer = get_writer()

    if args.bootstrap:
        writer.bootstrap_indices()
        print("Indices bootstrapped.")

    if args.health:
        h = writer.health()
        print(json.dumps(h, indent=2))

    if args.replay_dlq:
        writer.replay_dead_letter()

    if args.write_scores:
        df = pd.read_csv(args.write_scores)
        ok, fail = writer.write_anomaly_scores(df, only_anomalies=True)
        print(f"Written: {ok:,} success | {fail:,} failed")