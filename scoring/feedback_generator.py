"""Turns evaluation results into feedback a student can act on.

Every line here is derived from a recorded finding: nothing is invented, and
suggestions keep the name of the metric they came from. Objective diagnostics and
optional LLM remarks stay in separate fields.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, List

from models.results import CompileResult, Counterexample, MetricStatus, to_plain

if TYPE_CHECKING:
    from agent.result_manager import Evaluation

_MISSING_HEADER = re.compile(r"'?([\w./]+\.h)'? file not found|([\w./]+\.h): No such file")
_UNDECLARED = re.compile(r"use of undeclared identifier '(\w+)'|'(\w+)' undeclared")
_IMPLICIT = re.compile(r"implicit declaration of function '(\w+)'|"
                       r"call to undeclared function '(\w+)'")


def explain_compile_failure(result: CompileResult) -> List[str]:
    """Plain-language notes for the first few compiler errors."""
    if result.timed_out:
        return [f"Compilation was stopped: {result.error}."]
    notes = []
    for item in result.diagnostics:
        if item.severity != "error":
            continue
        where = f"Line {item.line}: " if item.line else ""
        missing = _MISSING_HEADER.search(item.message)
        undeclared = _UNDECLARED.search(item.message)
        implicit = _IMPLICIT.search(item.message)
        if missing:
            header = missing.group(1) or missing.group(2)
            notes.append(f"{where}the header {header} could not be found. Check its name.")
        elif implicit:
            name = implicit.group(1) or implicit.group(2)
            notes.append(f"{where}{name} is used without a declaration. "
                         "Include the right header or declare it first.")
        elif undeclared:
            name = undeclared.group(1) or undeclared.group(2)
            notes.append(f"{where}'{name}' is not declared. Check the spelling and scope.")
        else:
            notes.append(f"{where}{item.message}")
        if len(notes) == 5:
            break
    return notes or ([result.error] if result.error else ["Compilation failed."])


def _select_counterexamples(metrics: List[Any], limit: int) -> List[Counterexample]:
    """Prefer one failure per outcome or category over many of the same kind."""
    candidates: List[Counterexample] = []
    for metric in metrics:
        candidates.extend(metric.result.counterexamples)
    chosen, seen = [], set()
    for item in candidates:
        key = (item.origin, item.category or item.outcome)
        if key not in seen:
            seen.add(key)
            chosen.append(item)
    remaining = [item for item in candidates if item not in chosen]
    return (chosen + remaining)[:limit]


def build_feedback(evaluation: "Evaluation") -> Dict[str, Any]:
    limit = evaluation.report_settings["max_counterexamples"]
    suggestions: List[Dict[str, Any]] = []
    if not evaluation.first_pass.compiled:
        for note in explain_compile_failure(evaluation.compile_result):
            suggestions.append({"metric": "compilation", "marks_lost": None, "text": note})

    ranked = sorted(evaluation.metrics,
                    key=lambda metric: metric.contribution - metric.max_contribution)
    for metric in ranked:
        lost = round(metric.max_contribution - metric.contribution, 2)
        for text in metric.result.suggestions:
            suggestions.append({"metric": metric.name, "marks_lost": lost, "text": text})

    skipped: List[Dict[str, str]] = []
    for metric in evaluation.metrics:
        result = metric.result
        if result.status in (MetricStatus.NOT_EVALUATED, MetricStatus.BLOCKED):
            skipped.append({"check": metric.name, "status": result.status.value,
                            "reason": result.reason})
        for tool in result.skipped_tools:
            skipped.append({"check": f"{metric.name}/{tool['tool']}", "status": "skipped",
                            "reason": tool["reason"]})

    advisory: List[str] = []
    for metric in evaluation.metrics:
        llm = metric.result.evidence.get("llm", {})
        if llm.get("status") == "ok":
            advisory.extend(llm.get("reasons", []))
    return {
        "where_you_failed": to_plain(_select_counterexamples(evaluation.metrics, limit)),
        "suggestions": suggestions,
        "skipped_checks": skipped,
        "advisory_llm_remarks": advisory,
    }
