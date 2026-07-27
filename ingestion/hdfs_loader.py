"""
hdfs_loader.py
--------------
Step 1 of the pipeline: Upload the raw HDFS.log dataset from local disk
into Hadoop HDFS under /logsense/raw_logs/.

HDFS is primary storage (project requirement).
Kafka producer will later READ from HDFS, not from local disk.

Run once before starting the pipeline:
    python -m ingestion.hdfs_loader
"""

from __future__ import annotations

import time
from pathlib import Path

from config.settings import DatasetConfig, HDFSConfig
from utils.hdfs_client import (
    file_exists,
    initialize_hdfs_layout,
    upload_file,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# Destination path in HDFS for the raw log file
HDFS_RAW_LOG_DEST = f"{HDFSConfig.RAW_LOGS_PATH}/HDFS.log"

# Preprocessed files → upload to HDFS templates/sequences paths
PREPROCESSED_UPLOADS: list[tuple[Path, str]] = [
    (
        DatasetConfig.TEMPLATES_CSV,
        f"{HDFSConfig.TEMPLATES_PATH}/HDFS.log_templates.csv",
    ),
    (
        DatasetConfig.EVENT_TRACES_CSV,
        f"{HDFSConfig.EVENT_SEQUENCES_PATH}/Event_traces.csv",
    ),
    (
        DatasetConfig.OCCURRENCE_MATRIX_CSV,
        f"{HDFSConfig.EVENT_SEQUENCES_PATH}/Event_occurrence_matrix.csv",
    ),
    (
        DatasetConfig.ANOMALY_LABELS_CSV,
        f"{HDFSConfig.ANOMALIES_PATH}/anomaly_label.csv",
    ),
]


def upload_raw_log(force: bool = False) -> str:
    """
    Upload HDFS.log to Hadoop HDFS.

    Args:
        force: If True, re-upload even if file already exists in HDFS.

    Returns:
        HDFS path where file was uploaded.
    """
    logger.info("=== HDFS Raw Log Upload ===")
    DatasetConfig.validate()

    local_path = DatasetConfig.RAW_LOG
    hdfs_dest = HDFS_RAW_LOG_DEST

    if file_exists(hdfs_dest) and not force:
        logger.info(
            "Raw log already exists in HDFS at {}. Skipping upload. "
            "Use force=True to re-upload.",
            hdfs_dest,
        )
        return hdfs_dest

    file_size_gb = local_path.stat().st_size / (1024 ** 3)
    logger.info(
        "Uploading {:.2f} GB file: {} → HDFS:{}",
        file_size_gb,
        local_path,
        hdfs_dest,
    )

    start = time.perf_counter()
    upload_file(local_path, hdfs_dest, overwrite=force)
    elapsed = time.perf_counter() - start

    logger.success(
        "Raw log upload done in {:.1f}s ({:.2f} GB)",
        elapsed,
        file_size_gb,
    )
    return hdfs_dest


def upload_preprocessed_files(force: bool = False) -> None:
    """
    Upload all preprocessed dataset files (templates, traces, labels)
    to their respective HDFS paths.
    """
    logger.info("=== HDFS Preprocessed Files Upload ===")

    for local_path, hdfs_dest in PREPROCESSED_UPLOADS:
        if not local_path.exists():
            logger.warning("Skipping missing file: {}", local_path)
            continue

        if file_exists(hdfs_dest) and not force:
            logger.info("Already in HDFS, skipping: {}", hdfs_dest)
            continue

        upload_file(local_path, hdfs_dest, overwrite=force)

    logger.success("All preprocessed files uploaded to HDFS.")


def run_initial_setup(force: bool = False) -> None:
    """
    Full one-time setup:
    1. Create HDFS directory layout
    2. Upload raw HDFS.log
    3. Upload preprocessed files
    """
    logger.info("=== LogSense AI — HDFS Initial Setup ===")
    initialize_hdfs_layout()
    upload_raw_log(force=force)
    upload_preprocessed_files(force=force)
    logger.success("HDFS setup complete. Pipeline is ready to run.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Upload dataset to HDFS")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-upload files even if they already exist in HDFS",
    )
    args = parser.parse_args()
    run_initial_setup(force=args.force)