"""
drain_parser.py
---------------
Run Drain3 log parser on HDFS.log to extract event templates.

Two-phase approach:
1. Train Drain3 on HDFS.log → produce our_templates.csv
2. Validate our templates against Loghub's HDFS.log_templates.csv
   (compute match accuracy — shows professor we implemented + verified Drain)

Output: /logsense/templates/drain_templates.json (uploaded to HDFS)

Drain3 produces templates like:
    "PacketResponder <*> for block <*>" → E_our_001

We then cross-reference with the official 29 EventIDs (E1–E29) from Loghub.

Run:
    python -m parsing.drain_parser
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

from config.settings import DatasetConfig, HDFSConfig
from utils.hdfs_client import write_text
from utils.logger import get_logger

logger = get_logger(__name__)

# Output paths
LOCAL_DRAIN_OUTPUT = Path("data/preprocessed/drain_output.csv")
HDFS_TEMPLATES_JSON = f"{HDFSConfig.TEMPLATES_PATH}/drain_templates.json"


# ─── Drain3 configuration ────────────────────────────────────────────────────

def _build_drain_config() -> TemplateMinerConfig:
    """
    Configure Drain3 for HDFS log format.

    Key parameters for HDFS logs:
    - depth=4: HDFS log tree depth (date/time/level/component structure)
    - sim_th=0.5: similarity threshold (0.5 balances over/under grouping)
    - max_children=100: max branches per node
    - parametrize_numeric_tokens=True: replace numbers with <*>
    """
    config = TemplateMinerConfig()
    config.drain_depth = 4
    config.drain_sim_th = 0.5
    config.drain_max_children = 100
    config.drain_max_clusters = 1024
    config.parametrize_numeric_tokens = True
    # Masking rules — replace IPs and block IDs before Drain sees them
    config.masking = [
        {"regex_pattern": r"blk_[-\d]+", "mask_with": "<BLOCK>"},
        {"regex_pattern": r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?", "mask_with": "<IP>"},
        {"regex_pattern": r"(?<=[^A-Za-z0-9])(\-?\+?\d+)(?=[^A-Za-z0-9])|[0-9]+$", "mask_with": "<NUM>"},
    ]
    return config


# ─── Log line parser ─────────────────────────────────────────────────────────

# HDFS.log format:
# 081109 203518 143 INFO dfs.DataNode$DataXceiver: Receiving block blk_xxx ...
_RAW_LOG_PATTERN = re.compile(
    r"^(?P<date>\d{6})\s+"
    r"(?P<time>\d{6})\s+"
    r"(?P<pid>\d+)\s+"
    r"(?P<level>\w+)\s+"
    r"(?P<component>\S+):\s+"
    r"(?P<content>.+)$"
)


def _extract_content(raw_line: str) -> str | None:
    """Extract the log content (message body) from a raw HDFS log line."""
    match = _RAW_LOG_PATTERN.match(raw_line.strip())
    if match:
        return match.group("content")
    return None


# ─── Training ────────────────────────────────────────────────────────────────

@dataclass
class DrainResult:
    """Holds the trained Drain3 template miner and its output."""
    miner: TemplateMiner
    templates: list[dict] = field(default_factory=list)
    total_lines: int = 0
    parsed_lines: int = 0
    skipped_lines: int = 0


def train_drain(
    log_path: Path = DatasetConfig.RAW_LOG,
    sample_size: int | None = None,
) -> DrainResult:
    """
    Train Drain3 on HDFS.log.

    Args:
        log_path:    Path to raw HDFS.log
        sample_size: If set, only train on first N lines (for fast testing).
                     Use None to train on full 11M logs.

    Returns:
        DrainResult with trained miner and discovered templates.
    """
    logger.info("=== Drain3 Training ===")
    logger.info("Log file: {} | Sample: {}", log_path, sample_size or "full")

    if not log_path.exists():
        raise FileNotFoundError(f"Log file not found: {log_path}")

    config = _build_drain_config()
    miner = TemplateMiner(config=config)
    result = DrainResult(miner=miner)

    logger.info("Starting Drain3 training...")

    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            result.total_lines += 1

            if sample_size and result.total_lines > sample_size:
                break

            content = _extract_content(raw_line)
            if content is None:
                result.skipped_lines += 1
                continue

            miner.add_log_message(content)
            result.parsed_lines += 1

            if result.total_lines % 500_000 == 0:
                logger.info(
                    "Drain progress: {:,} lines processed | {:,} templates found",
                    result.total_lines,
                    len(miner.drain.clusters),
                )

    # Extract discovered templates
    result.templates = [
        {
            "cluster_id": str(cluster.cluster_id),
            "template": cluster.get_template(),
            "size": cluster.size,
        }
        for cluster in miner.drain.clusters
    ]

    logger.success(
        "Drain3 training complete: {:,} lines → {} templates "
        "(skipped: {:,})",
        result.parsed_lines,
        len(result.templates),
        result.skipped_lines,
    )
    return result


# ─── Validation against Loghub benchmark ─────────────────────────────────────

def validate_against_loghub(
    drain_result: DrainResult,
    loghub_templates_path: Path = DatasetConfig.TEMPLATES_CSV,
) -> dict:
    """
    Compare our Drain3 templates against the official Loghub templates (E1–E29).

    Matching strategy: for each official template keyword, check if any of
    our discovered templates contain the same key tokens.

    Returns a dict with match statistics for the professor report.
    """
    logger.info("=== Validating against Loghub Templates ===")

    if not loghub_templates_path.exists():
        logger.warning(
            "Loghub templates file not found: {}. Skipping validation.",
            loghub_templates_path,
        )
        return {"status": "skipped", "reason": "file not found"}

    # Load official templates
    loghub_df = pd.read_csv(loghub_templates_path)
    logger.info("Official Loghub templates: {}", len(loghub_df))

    # Our templates as a flat list
    our_templates = [t["template"].lower() for t in drain_result.templates]

    # Match count
    matched = 0
    match_details = []

    for _, row in loghub_df.iterrows():
        event_id = row.get("EventId", row.get("EventID", ""))
        official_template = str(row.get("EventTemplate", "")).lower()

        # Extract key tokens (non-wildcard words)
        key_tokens = [
            w for w in official_template.split()
            if w not in ("<*>", "<block>", "<ip>", "<num>") and len(w) > 3
        ]
        if not key_tokens:
            continue

        # Check if any of our templates contains all key tokens
        our_match = next(
            (t for t in our_templates if all(tok in t for tok in key_tokens)),
            None,
        )

        if our_match:
            matched += 1
            match_details.append({
                "event_id": event_id,
                "official": official_template,
                "our_match": our_match,
                "status": "matched",
            })
        else:
            match_details.append({
                "event_id": event_id,
                "official": official_template,
                "our_match": None,
                "status": "not_matched",
            })

    total_official = len(loghub_df)
    match_pct = (matched / total_official * 100) if total_official > 0 else 0

    stats = {
        "total_official_templates": total_official,
        "total_our_templates": len(drain_result.templates),
        "matched": matched,
        "not_matched": total_official - matched,
        "match_accuracy_pct": round(match_pct, 2),
        "details": match_details,
    }

    logger.success(
        "Validation: {}/{} official templates matched ({:.1f}%)",
        matched,
        total_official,
        match_pct,
    )

    return stats


# ─── Save and upload ──────────────────────────────────────────────────────────

def save_templates_locally(
    drain_result: DrainResult,
    output_path: Path = LOCAL_DRAIN_OUTPUT,
) -> None:
    """Save our discovered templates to a local CSV for inspection."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(drain_result.templates)
    df.to_csv(output_path, index=False)
    logger.info("Templates saved locally: {} ({} rows)", output_path, len(df))


def upload_templates_to_hdfs(drain_result: DrainResult) -> None:
    """
    Serialize Drain3 templates to JSON and upload to HDFS.
    This JSON file is loaded by template_mapper.py as a broadcast variable.
    """
    templates_json = json.dumps(drain_result.templates, indent=2)
    write_text(HDFS_TEMPLATES_JSON, templates_json)
    logger.success("Templates uploaded to HDFS: {}", HDFS_TEMPLATES_JSON)


# ─── Main entry point ─────────────────────────────────────────────────────────

def run_drain_pipeline(sample_size: int | None = None) -> DrainResult:
    """
    Full Drain pipeline:
    1. Train Drain3 on HDFS.log
    2. Validate against Loghub templates
    3. Save locally
    4. Upload to HDFS
    """
    result = train_drain(sample_size=sample_size)
    validation = validate_against_loghub(result)

    save_templates_locally(result)
    upload_templates_to_hdfs(result)

    logger.info(
        "Drain pipeline done. Match accuracy: {}%",
        validation.get("match_accuracy_pct", "N/A"),
    )
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run Drain3 log parser")
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Train on first N lines only (omit for full dataset)",
    )
    args = parser.parse_args()

    run_drain_pipeline(sample_size=args.sample)