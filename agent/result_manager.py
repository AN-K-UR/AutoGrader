"""Holds one evaluation's state: its temporary directory and its collected results."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from models.results import CompileResult, FirstPass, MetricResult, ScoreSummary


class Workspace:
    """A private temporary directory, always removed on exit."""

    def __init__(self, keep: bool = False) -> None:
        self.keep = keep
        self.path = ""

    def __enter__(self) -> "Workspace":
        # realpath: on macOS /var is a symlink, which sandbox profiles do not follow.
        self.path = os.path.realpath(tempfile.mkdtemp(prefix="autograder-"))
        return self

    def __exit__(self, *_: Any) -> None:
        if self.path and not self.keep:
            shutil.rmtree(self.path, ignore_errors=True)


@dataclass
class Evaluation:
    """Everything known about a graded submission, before report formatting."""

    submission_id: str
    source_name: str
    source_hash: str
    rules_name: str
    rules_hash: str
    testset_hash: Optional[str]
    problem: str
    backend: Dict[str, Any]
    first_pass: FirstPass
    compile_result: CompileResult
    compiler_version: str
    metrics: List[MetricResult]
    tool_versions: Dict[str, str]
    limits: Dict[str, Any]
    report_settings: Dict[str, Any]
    summary: Optional[ScoreSummary] = None
    feedback: Dict[str, Any] = field(default_factory=dict)
    flags: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc)
                           .strftime("%Y-%m-%dT%H:%M:%SZ"))

    def fingerprint(self) -> str:
        """Hash of everything that must be identical across repeat runs.

        Timestamps, durations, and advisory LLM text are excluded on purpose.
        """
        payload = {
            "source": self.source_hash,
            "rules": self.rules_hash,
            "tests": self.testset_hash,
            "grade": self.summary.grade if self.summary else None,
            "status": self.summary.status if self.summary else None,
            "metrics": [[metric.name, metric.result.status.value, metric.result.score]
                        for metric in self.metrics],
        }
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_text(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()
