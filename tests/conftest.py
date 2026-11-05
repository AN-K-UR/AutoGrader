"""Shared fixtures. Tests use harmless programs and never need a network or an LLM."""
import copy
import json
import shutil
import sys

import pytest

from agent.config_loader import load_rules
from agent.result_manager import Workspace
from analyzers.base import AnalysisContext
from analyzers.c_source import CSource
from execution.compiler import compile_source
from execution.sandbox import SeatbeltBackend, UnsafeBackend
from models.results import CompileResult, FirstPass

MINIMAL_RULES = {
    "problem": "demo",
    "time_limit_s": 1,
    "memory_limit_mb": 64,
    "metrics": [
        {"name": "modularity", "analyzer": "function_split", "weight": 0.5},
        {"name": "readability", "analyzer": "llm_review", "weight": 0.5},
    ],
}
ADD = """#include <stdio.h>
int main(void) {
    long long a, b;
    if (scanf("%lld %lld", &a, &b) != 2) { return 1; }
    printf("%lld\\n", a + b);
    return 0;
}
"""
needs_seatbelt = pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("sandbox-exec") is None,
    reason="sandbox-exec is unavailable")


@pytest.fixture
def backend():
    """A real isolated backend where possible; the harmless fixtures allow either."""
    seatbelt = SeatbeltBackend()
    return seatbelt if seatbelt.available()[0] else UnsafeBackend()


@pytest.fixture
def rules_factory(tmp_path):
    """Write a rules document to disk and load it, as the real agent does."""
    def build(overrides=None, metrics=None):
        document = copy.deepcopy(MINIMAL_RULES)
        document.update(overrides or {})
        if metrics is not None:
            document["metrics"] = metrics
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return load_rules(str(path))
    return build


@pytest.fixture
def workdir():
    with Workspace() as workspace:
        yield workspace.path


@pytest.fixture
def context_factory(backend, rules_factory, workdir):
    """Build an AnalysisContext around real compiled source."""
    def build(source_text, metrics=None, overrides=None, compile_it=True):
        rules = rules_factory(overrides, metrics)
        with open(f"{workdir}/submission.c", "w", encoding="utf-8") as handle:
            handle.write(source_text)
        result = CompileResult(False, "gcc", [])
        if compile_it:
            result = compile_source(backend, "gcc", ["submission.c"], "submission.bin",
                                    ["-O2", "-std=c11", "-w"], workdir, 20, ["-lm"])
        return AnalysisContext(
            source_name="submission.c", source_file="submission.c",
            source=CSource(source_text), rules=rules, backend=backend, workdir=workdir,
            compile_result=result, first_pass=FirstPass(compiled=result.success),
            binary=result.binary)
    return build


@pytest.fixture
def write_tests(tmp_path):
    """Create a test directory from (id, input, expected) triples."""
    def build(cases, name="tests"):
        directory = tmp_path / name
        directory.mkdir(exist_ok=True)
        for test_id, given, expected in cases:
            (directory / f"{test_id}.in").write_text(given)
            (directory / f"{test_id}.out").write_text(expected)
        return directory
    return build
