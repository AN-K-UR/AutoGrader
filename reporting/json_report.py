"""Builds the machine-readable report. The text report is rendered from this dict.

Both reports come from one object, so they cannot disagree on the grade.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from agent.result_manager import Evaluation
from models.results import to_plain

SCHEMA_VERSION = "1.0"
_LIMITATIONS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "config", "usefulness_limitations.json")


def clip_text(text: str, max_bytes: int) -> str:
    """Bound a string by encoded size, and say how much was removed."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    removed = len(encoded) - max_bytes
    return encoded[:max_bytes].decode("utf-8", errors="ignore") + f"...[{removed} bytes removed]"


def clip_tree(value: Any, max_bytes: int) -> Any:
    """Apply :func:`clip_text` to every string in a JSON-like structure."""
    if isinstance(value, str):
        return clip_text(value, max_bytes)
    if isinstance(value, dict):
        return {key: clip_tree(item, max_bytes) for key, item in value.items()}
    if isinstance(value, list):
        return [clip_tree(item, max_bytes) for item in value]
    return value


def _load_usefulness_limitations() -> Optional[Dict[str, Any]]:
    try:
        with open(_LIMITATIONS_FILE, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def build_report(evaluation: Evaluation) -> Dict[str, Any]:
    settings = evaluation.report_settings
    summary = evaluation.summary
    compile_result = evaluation.compile_result
    metrics = []
    for metric in evaluation.metrics:
        result = metric.result
        metrics.append({
            "name": metric.name,
            "analyzer": metric.analyzer,
            "status": result.status.value,
            "score": result.score,
            "weight": metric.weight,
            "contribution": metric.contribution,
            "max_contribution": metric.max_contribution,
            "threshold": metric.threshold,
            "met_threshold": metric.met_threshold,
            "feedback": result.feedback,
            "evidence": to_plain(result.evidence),
            "counterexamples": to_plain(result.counterexamples)[:settings["max_findings"]],
        })
    report: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "submission": evaluation.source_name,
        "submission_id": evaluation.submission_id,
        "problem": evaluation.problem,
        "source_hash": evaluation.source_hash,
        "rules_file": evaluation.rules_name,
        "rules_hash": evaluation.rules_hash,
        "testset_hash": evaluation.testset_hash,
        "timestamp": evaluation.timestamp,
        "grade": summary.grade,
        "evaluation_status": summary.status,
        "grade_fingerprint": evaluation.fingerprint(),
        "scoring": to_plain(summary),
        "first_pass": to_plain(evaluation.first_pass),
        "compilation": {
            "success": compile_result.success,
            "compiler": compile_result.compiler,
            "compiler_version": evaluation.compiler_version,
            "flags": compile_result.flags,
            "exit_code": compile_result.exit_code,
            "output": compile_result.output,
            "diagnostics": to_plain(compile_result.diagnostics),
        },
        "execution": dict(evaluation.backend, limits=evaluation.limits),
        "metrics": metrics,
        "flags": evaluation.flags,
        "feedback": evaluation.feedback,
        "tool_versions": evaluation.tool_versions,
    }
    if settings["include_usefulness_limitations"]:
        report["usefulness_limitations"] = _load_usefulness_limitations()
    return clip_tree(report, settings["max_text_bytes"])


def write_json(report: Dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=False, ensure_ascii=False)
        handle.write("\n")
