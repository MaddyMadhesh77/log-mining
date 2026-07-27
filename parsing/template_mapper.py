"""
template_mapper.py
------------------
Builds a regex-based template → EventID mapping for use in Spark Streaming.

Two sources (in priority order):
1. Official Loghub HDFS.log_templates.csv  (E1–E29, most precise)
2. Our Drain3 output drain_output.csv       (our trained templates)

The final map is a Python dict:
    {compiled_regex_pattern: "E5", ...}

In Spark Streaming, this dict is broadcast to all workers (O(1) lookup per log line).

Usage in Spark:
    mapper = TemplateMapper()
    mapper.load()
    broadcast_map = spark.sparkContext.broadcast(mapper.get_regex_map())
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from config.settings import DatasetConfig
from utils.logger import get_logger

logger = get_logger(__name__)

# Fallback local Drain output (produced by drain_parser.py)
LOCAL_DRAIN_OUTPUT = Path("data/preprocessed/drain_output.csv")


@dataclass
class TemplateMapper:
    """
    Loads event templates and builds a compiled regex lookup map.

    Attributes:
        event_map: dict of {EventID: template_string}
        regex_map: list of (compiled_pattern, EventID) tuples — ordered by specificity
    """
    event_map: dict[str, str] = field(default_factory=dict)
    regex_map: list[tuple[re.Pattern, str]] = field(default_factory=list)
    _loaded: bool = False

    def load(self) -> "TemplateMapper":
        """
        Load templates from Loghub official CSV, falling back to our Drain output.
        Builds and compiles regex patterns for fast matching.
        """
        if self._loaded:
            return self

        logger.info("=== Loading Event Template Map ===")

        # Try official Loghub templates first
        if DatasetConfig.TEMPLATES_CSV.exists():
            logger.info(
                "Using official Loghub templates: {}",
                DatasetConfig.TEMPLATES_CSV,
            )
            self.event_map = self._load_loghub_templates(
                DatasetConfig.TEMPLATES_CSV
            )
        elif LOCAL_DRAIN_OUTPUT.exists():
            logger.info(
                "Official templates not found. "
                "Falling back to our Drain output: {}",
                LOCAL_DRAIN_OUTPUT,
            )
            self.event_map = self._load_drain_templates(LOCAL_DRAIN_OUTPUT)
        else:
            raise FileNotFoundError(
                "No template file found. Run drain_parser.py first, "
                "or ensure HDFS.log_templates.csv is in data/preprocessed/"
            )

        # Compile regex patterns — longer patterns matched first (more specific)
        self.regex_map = self._compile_patterns(self.event_map)
        self._loaded = True

        logger.success(
            "TemplateMapper ready: {} event templates loaded, {} regex patterns compiled",
            len(self.event_map),
            len(self.regex_map),
        )
        return self

    # ─── Loaders ─────────────────────────────────────────────────────────────

    @staticmethod
    def _load_loghub_templates(path: Path) -> dict[str, str]:
        """
        Parse official Loghub HDFS.log_templates.csv.

        Expected columns: EventId, EventTemplate
        E.g.: E1, "<*> Adding an already existing block <*>"
        """
        df = pd.read_csv(path)

        # Normalize column names
        df.columns = [c.strip() for c in df.columns]

        event_id_col = next(
            (c for c in df.columns if "eventid" in c.lower()), None
        )
        template_col = next(
            (c for c in df.columns if "template" in c.lower()), None
        )

        if not event_id_col or not template_col:
            raise ValueError(
                f"Expected columns 'EventId' and 'EventTemplate' in {path}. "
                f"Found: {list(df.columns)}"
            )

        event_map = {}
        for _, row in df.iterrows():
            event_id = str(row[event_id_col]).strip()
            template = str(row[template_col]).strip()
            if event_id and template:
                event_map[event_id] = template

        logger.info("Loaded {} official Loghub templates", len(event_map))
        return event_map

    @staticmethod
    def _load_drain_templates(path: Path) -> dict[str, str]:
        """
        Parse our Drain3 output CSV.
        Assigns synthetic event IDs: D1, D2, D3...
        """
        df = pd.read_csv(path)
        event_map = {}
        for i, row in df.iterrows():
            event_id = f"D{i + 1}"
            template = str(row.get("template", "")).strip()
            if template:
                event_map[event_id] = template

        logger.info("Loaded {} Drain3 templates", len(event_map))
        return event_map

    # ─── Pattern compilation ──────────────────────────────────────────────────

    @staticmethod
    def _template_to_regex(template: str) -> str:
        # Convert Loghub [*] → unified wildcard token
        template = template.replace("[*]", "<*>")

        # Split on wildcard tokens, preserving them
        parts = re.split(r"(<\*>|<BLOCK>|<IP>|<NUM>)", template)
        regex_parts = []

        for part in parts:
            if part in ("<*>", "<IP>", "<NUM>"):
                regex_parts.append(r".*?")       # lazy match — can match empty too
            elif part == "<BLOCK>":
                regex_parts.append(r"blk_-?\d+")
            elif part:                            # skip empty strings from split edges
                escaped = re.escape(part)
                escaped = escaped.replace(r"\ ", r"\s+")
                regex_parts.append(escaped)

        return "".join(regex_parts)             # direct concat — no \s* join

    def _compile_patterns(
        self, event_map: dict[str, str]
    ) -> list[tuple[re.Pattern, str]]:
        """
        Compile all templates to regex patterns.
        Sort by template length descending — longer patterns are more specific
        and should be tried first to avoid partial matches.
        """
        compiled = []
        for event_id, template in event_map.items():
            try:
                pattern_str = self._template_to_regex(template)
                # Use IGNORECASE for robustness
                compiled_pattern = re.compile(
                    pattern_str, re.IGNORECASE
                )
                compiled.append((compiled_pattern, event_id))
            except re.error as exc:
                logger.warning(
                    "Failed to compile template for {}: {} | Error: {}",
                    event_id,
                    template,
                    exc,
                )

        # Sort by raw template length descending (more specific first)
        compiled.sort(
            key=lambda x: len(event_map[x[1]]),
            reverse=True,
        )
        return compiled

    # ─── Lookup ──────────────────────────────────────────────────────────────

    def match(self, log_content: str) -> str:
        """
        Match a log content string against all compiled templates.

        Returns the EventID of the first matching template.
        Returns "E_UNKNOWN" if no template matches.

        Args:
            log_content: The message body of a log line
                         (after removing date/time/pid/level/component prefix)
        """
        if not self._loaded:
            self.load()

        for pattern, event_id in self.regex_map:
            if pattern.search(log_content):
                return event_id

        return "E_UNKNOWN"

    def get_event_map(self) -> dict[str, str]:
        """Returns raw {EventID: template_string} dict."""
        if not self._loaded:
            self.load()
        return self.event_map

    def get_serializable_map(self) -> list[tuple[str, str]]:
        """
        Returns templates as list of (pattern_string, EventID) tuples.
        Safe to broadcast via Spark — compiled patterns are NOT picklable.
        Spark workers call re.compile() on their side using this list.
        """
        if not self._loaded:
            self.load()

        return [
            (self._template_to_regex(template), event_id)
            for event_id, template in self.event_map.items()
        ]


# ─── Module-level singleton for convenience ──────────────────────────────────

_mapper: TemplateMapper | None = None


def get_mapper() -> TemplateMapper:
    """Returns a loaded singleton TemplateMapper."""
    global _mapper
    if _mapper is None:
        _mapper = TemplateMapper().load()
    return _mapper


if __name__ == "__main__":
    # Quick sanity test
    mapper = get_mapper()

    test_lines = [
    "PacketResponder 1 for block blk_-1608999687919862906 terminating",
    "Receiving block blk_-1608999687919862906 src: /10.250.19.102:54106 dest: /10.250.19.102:50010",  # ← add dest:
    "BLOCK* NameSystem.allocateBlock: /mnt/hadoop/mapred/job.jar. blk_123",
    "Verification succeeded for blk_-1608999687919862906",
    ]

    print("\nTemplate Mapper — Sanity Check")
    print("=" * 60)
    for line in test_lines:
        event_id = mapper.match(line)
        print(f"[{event_id:12s}] {line[:70]}")