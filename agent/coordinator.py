"""The main agent: runs the first pass, dispatches analyzers, collates the result."""
from __future__ import annotations

import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from agent.config_loader import Metric, Rules
from agent.first_pass import run_first_pass
from agent.result_manager import Evaluation, Workspace, sha256_text
from analyzers.base import AnalysisContext, get_analyzer
from analyzers.c_source import CSource
from analyzers.static_analysis import find_tool
from analyzers.testset import hash_testset
from execution.sandbox import ExecutionBackend, UnsafeBackend, select_backend
from models.results import AnalyzerResult, MetricResult, MetricStatus
from scoring.feedback_generator import build_feedback
from scoring.score_calculator import calculate_score

log = logging.getLogger("autograder")

MAX_SOURCE_BYTES = 1_000_000
_PRIVATE_SOURCE_NAME = "submission.c"
_MAX_SOURCE_WORKERS = 4


class SubmissionError(ValueError):
    """The submission path itself is unusable, so there is nothing to grade."""


def read_submission(path: str) -> bytes:
    if not path.endswith(".c"):
        raise SubmissionError(f"expected a .c file, got {os.path.basename(path)}")
    if not os.path.isfile(path):
        raise SubmissionError(f"submission not found: {path}")
    if os.path.getsize(path) > MAX_SOURCE_BYTES:
        raise SubmissionError(f"submission is larger than {MAX_SOURCE_BYTES} bytes")
    with open(path, "rb") as handle:
        return handle.read()


def _tool_versions(backend: ExecutionBackend, rules: Rules, workdir: str) -> Dict[str, str]:
    versions = {"compiler": backend.compiler_version(rules.execution["compiler"], workdir)}
    try:
        import lizard
        versions["lizard"] = lizard.version
    except ImportError:
        versions["lizard"] = "not installed"
    cppcheck = find_tool("cppcheck")
    versions["cppcheck"] = "installed" if cppcheck else "not installed"
    if cppcheck:
        import subprocess
        try:
            versions["cppcheck"] = subprocess.run(
                [cppcheck, "--version"], capture_output=True, text=True, timeout=10,
                check=False).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return versions


def _run_one(metric: Metric, context: AnalysisContext) -> AnalyzerResult:
    """Run one analyzer; an internal failure becomes data, not a lost evaluation."""
    analyzer = get_analyzer(metric.analyzer)()
    try:
        return analyzer.run(context, metric.params)
    except Exception as error:  # pylint: disable=broad-except
        log.exception("analyzer %s failed", metric.analyzer)
        return AnalyzerResult.not_evaluated(f"analyzer failed internally: {error}")


def _blocked_reason(context: AnalysisContext) -> Optional[str]:
    first = context.first_pass
    if not first.compiled:
        return "skipped: the program does not compile"
    if first.suspected_infinite_loop:
        return "skipped: the smoke run timed out (suspected infinite loop)"
    if first.smoke_crashed and context.rules.first_pass["fail_on_smoke_crash"]:
        return "skipped: the smoke run crashed"
    return None


def dispatch(rules: Rules, context: AnalysisContext) -> List[MetricResult]:
    """Run each enabled analyzer once and return results in rule order.

    Source-only analyzers run in parallel. Execution analyzers run one at a time,
    because concurrent load could push a borderline program past its time limit
    and break the reproducibility contract.
    """
    results: Dict[str, AnalyzerResult] = {}
    blocked = _blocked_reason(context)
    source_only, executing = [], []
    for metric in rules.metrics:
        if not metric.enabled:
            results[metric.name] = AnalyzerResult(status=MetricStatus.DISABLED,
                                                  feedback="disabled by the rules")
        elif get_analyzer(metric.analyzer).needs_execution:
            executing.append(metric)
        else:
            source_only.append(metric)

    with ThreadPoolExecutor(max_workers=_MAX_SOURCE_WORKERS) as pool:
        futures = {metric.name: pool.submit(_run_one, metric, context) for metric in source_only}
    for name, future in futures.items():
        results[name] = future.result()

    for metric in executing:
        results[metric.name] = (AnalyzerResult.blocked(blocked) if blocked
                                else _run_one(metric, context))

    collated = []
    for metric in rules.metrics:
        result = results[metric.name]
        met = None
        if metric.threshold is not None and result.score is not None:
            met = result.score >= metric.threshold
        collated.append(MetricResult(metric.name, metric.analyzer, metric.weight, result,
                                     metric.threshold, met))
    return collated


def _collect_flags(context: AnalysisContext, metrics: List[MetricResult]) -> List[Dict]:
    flags: List[Dict] = []
    first = context.first_pass
    if not first.compiled:
        flags.append({"type": "compilation_failed"})
    if first.suspected_infinite_loop:
        flags.append({"type": "suspected_infinite_loop"})
    if first.smoke_crashed:
        flags.append({"type": "smoke_crashed", "detail": first.smoke_detail})
    for metric in metrics:
        flags.extend(metric.result.flags)
    return flags


def evaluate(source_path: str, rules: Rules, allow_unsafe: bool = False,
             keep_workspace: bool = False, allow_llm: bool = True) -> Evaluation:
    """Grade one submission end to end, unattended."""
    content = read_submission(source_path)
    backend = select_backend(rules.execution["backend"], rules.execution["docker_image"],
                             allow_unsafe)
    if isinstance(backend, UnsafeBackend):
        log.warning("UNSAFE backend in use: the submission runs without isolation")

    source = CSource(content.decode("utf-8", errors="replace"))
    with Workspace(keep=keep_workspace) as workspace:
        workdir = workspace.path
        shutil.copyfile(source_path, os.path.join(workdir, _PRIVATE_SOURCE_NAME))
        first_pass, compile_result = run_first_pass(rules, backend, workdir,
                                                    _PRIVATE_SOURCE_NAME, source)
        context = AnalysisContext(
            source_name=os.path.basename(source_path),
            source_file=_PRIVATE_SOURCE_NAME,
            source=source,
            rules=rules,
            backend=backend,
            workdir=workdir,
            compile_result=compile_result,
            first_pass=first_pass,
            binary=compile_result.binary,
            original_path=os.path.abspath(source_path),
            allow_llm=allow_llm,
        )
        metrics = dispatch(rules, context)
        versions = _tool_versions(backend, rules, workdir)
        flags = _collect_flags(context, metrics)

    summary = calculate_score(metrics, rules.scoring, first_pass.compiled)
    testset = rules.first_testset()
    name = os.path.basename(source_path)
    evaluation = Evaluation(
        submission_id=f"{os.path.splitext(name)[0]}-{sha256_text(content)[7:15]}",
        source_name=name,
        source_hash=sha256_text(content),
        rules_name=os.path.basename(rules.path),
        rules_hash=rules.hash,
        testset_hash=hash_testset(testset) if testset else None,
        problem=rules.problem,
        backend={"name": backend.name, "isolated": backend.isolated,
                 "guarantees": backend.guarantees},
        first_pass=first_pass,
        compile_result=compile_result,
        compiler_version=versions["compiler"],
        metrics=metrics,
        tool_versions=versions,
        limits={"time_limit_s": rules.time_limit_s, "memory_limit_mb": rules.memory_limit_mb},
        report_settings=rules.report,
        summary=summary,
        flags=flags,
    )
    evaluation.feedback = build_feedback(evaluation)
    return evaluation
