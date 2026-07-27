"""
hdfs_client.py
--------------
Thin wrapper around the 'hdfs' Python client for Hadoop HDFS operations.

All LogSense HDFS operations go through this module:
    - upload_file / download_file
    - read_lines (streaming line-by-line — never loads full file)
    - write_text
    - file_exists / mkdir / list_dir
    - initialize_hdfs_layout (one-time setup)

The hdfs library connects via the WebHDFS REST API (port 50070 / 9870).
No native Hadoop install required on the client machine.

Install: pip install hdfs

Usage:
    from utils.hdfs_client import upload_file, read_lines, file_exists
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Iterator

from hdfs import InsecureClient
from hdfs.util import HdfsError

from config.settings import HDFSConfig
from utils.logger import get_logger

logger = get_logger(__name__)

# ─── Client singleton ─────────────────────────────────────────────────────────
_client: InsecureClient | None = None


def _get_client() -> InsecureClient:
    """
    Return a cached WebHDFS client.
    Creates a new one on first call.
    Uses InsecureClient (no Kerberos) — suitable for local/Docker HDFS.
    """
    global _client
    if _client is None:
        url = f"http://{HDFSConfig.NAMENODE_HOST}:9870"
        logger.info("Connecting to HDFS WebHDFS: {}", url)
        _client = InsecureClient(url, user=HDFSConfig.HDFS_USER)
        # Verify connection
        try:
            _client.status("/")
            logger.success("HDFS connection OK: {}", url)
        except HdfsError as exc:
            logger.error("HDFS connection failed: {}", exc)
            raise
    return _client

# Public alias for external imports
def get_client():
    """Public wrapper around _get_client()."""
    return _get_client()

# ─── Directory operations ─────────────────────────────────────────────────────

def mkdir(hdfs_path: str) -> None:
    """Create directory (and parents) in HDFS. No-op if already exists."""
    client = _get_client()
    try:
        client.makedirs(hdfs_path)
        logger.debug("HDFS mkdir: {}", hdfs_path)
    except HdfsError as exc:
        if "already exists" in str(exc).lower():
            pass  # Directory exists — that's fine
        else:
            logger.error("HDFS mkdir failed for {}: {}", hdfs_path, exc)
            raise


def initialize_hdfs_layout() -> None:
    """
    Create the full LogSense directory tree in HDFS.
    Safe to run multiple times — skips existing directories.
    """
    logger.info("Initialising HDFS directory layout...")
    for path in HDFSConfig.ALL_DIRS:
        mkdir(path)
    logger.success("HDFS layout ready under {}", HDFSConfig.BASE_PATH)


def file_exists(hdfs_path: str) -> bool:
    """Return True if file/directory exists in HDFS."""
    client = _get_client()
    try:
        client.status(hdfs_path)
        return True
    except HdfsError:
        return False


def list_dir(hdfs_path: str) -> list[str]:
    """List files in an HDFS directory. Returns empty list if not found."""
    client = _get_client()
    try:
        return client.list(hdfs_path)
    except HdfsError:
        return []


# ─── File upload / download ───────────────────────────────────────────────────

def upload_file(
    local_path: Path,
    hdfs_path: str,
    overwrite: bool = False,
    chunk_size: int = 1024 * 1024,     # 1 MB chunks
) -> None:
    """
    Upload a local file to HDFS.

    Args:
        local_path:  Local file path (Path object)
        hdfs_path:   Destination HDFS path (string)
        overwrite:   If True, overwrite existing file
        chunk_size:  Upload chunk size in bytes (default 1 MB)
    """
    client = _get_client()

    if not local_path.exists():
        raise FileNotFoundError(f"Local file not found: {local_path}")

    logger.info(
        "Uploading {} → HDFS:{} (overwrite={})",
        local_path,
        hdfs_path,
        overwrite,
    )

    client.upload(
        hdfs_path,
        str(local_path),
        overwrite=overwrite,
        chunk_size=chunk_size,
    )

    # Verify upload
    status = client.status(hdfs_path)
    logger.success(
        "Upload complete: HDFS:{} | size={:.2f} MB",
        hdfs_path,
        status["length"] / (1024 * 1024),
    )


def download_file(
    hdfs_path: str,
    local_path: Path,
    overwrite: bool = False,
) -> None:
    """Download a file from HDFS to local disk."""
    client = _get_client()
    local_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Downloading HDFS:{} → {}", hdfs_path, local_path)
    client.download(hdfs_path, str(local_path), overwrite=overwrite)
    logger.success("Download complete: {}", local_path)


# ─── Streaming line reader ────────────────────────────────────────────────────

def read_lines(hdfs_path: str, encoding: str = "utf-8") -> Iterator[str]:
    client = _get_client()
    logger.debug("Streaming lines from HDFS:{}", hdfs_path)

    with client.read(hdfs_path, encoding=encoding, delimiter="\n") as reader:
        for line in reader:
            yield line


# ─── Text write ───────────────────────────────────────────────────────────────

def write_text(hdfs_path: str, content: str, overwrite: bool = True) -> None:
    """
    Write a string to an HDFS file.
    Used by drain_parser.py to upload templates JSON.
    """
    client = _get_client()
    encoded = content.encode("utf-8")
    with client.write(hdfs_path, overwrite=overwrite) as writer:
        writer.write(encoded)
    logger.info("Written to HDFS:{} ({} bytes)", hdfs_path, len(encoded))


# ─── Parquet helpers (Spark-agnostic) ────────────────────────────────────────

def hdfs_uri(path: str) -> str:
    """
    Convert a bare HDFS path to a full HDFS URI for Spark / pandas.

    Example:
        hdfs_uri("/logsense/parsed_logs") →
        "hdfs://localhost:9000/logsense/parsed_logs"
    """
    return (
        f"hdfs://{HDFSConfig.NAMENODE_HOST}:{HDFSConfig.NAMENODE_PORT}{path}"
    )