"""``sanitizer_run``: ASan/UBSan on real inputs, plus an allocation tracker.

Sanitizers only observe paths that execute, so "no diagnostics" means nothing was
found on these inputs. It is never reported as proof of memory safety.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from analyzers.base import AnalysisContext, Analyzer, register
from analyzers.testset import load_testset
from execution.compiler import compile_source, split_flags
from execution.process_runner import Limits
from execution.sandbox import ExecutionBackend
from models.results import AnalyzerResult

_RUNTIME = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "execution", "runtime", "leak_shim.c")
_ASAN = re.compile(r"ERROR: AddressSanitizer: ([\w-]+)")
_UBSAN = re.compile(r"(?:^|/)[\w.-]*\.c:(\d+):(\d+): runtime error: (.+)$", re.MULTILINE)
_UNSYMBOLIZED = re.compile(r"\((?:[^:()]+):\w+\+(0x[0-9a-f]+)\)")
_SYMBOLIZED = re.compile(r"\b[\w.-]+\.c:(\d+)")
_LEAK = re.compile(r"@@AG_LEAK:(\d+):(\d+)@@")
_VOLATILE = re.compile(r"0x[0-9a-fA-F]+|\d+")
_DEFAULT_PENALTIES = {"memory_error": 0.5, "undefined_behavior": 0.25, "leak": 0.25}
_SANITIZER_ENV = {
    "ASAN_OPTIONS": "detect_leaks=0:symbolize=0:abort_on_error=0:exitcode=99",
    "UBSAN_OPTIONS": "print_stacktrace=0",
}
_LEAK_DEFINES = ["-Dmalloc=ag_malloc", "-Dcalloc=ag_calloc", "-Dfree=ag_free",
                 "-Drealloc=ag_realloc", "-Dstrdup=ag_strdup"]


def _source_line(stderr: str, binary_path: str) -> Optional[int]:
    """Find the submission's line in an ASan report.

    Under the sandbox the sanitizer cannot launch its symbolizer, so raw offsets
    are resolved afterwards by the trusted host tool ``atos``.
    """
    match = _SYMBOLIZED.search(stderr)
    if match:
        return int(match.group(1))
    if shutil.which("atos") is None:
        return None
    for address in _UNSYMBOLIZED.findall(stderr)[:6]:
        try:
            done = subprocess.run(["atos", "-o", binary_path, address], capture_output=True,
                                  text=True, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        match = _SYMBOLIZED.search(done.stdout)
        if match:
            return int(match.group(1))
    return None


def parse_sanitizer_output(stderr: str, binary_path: str = "") -> List[Dict[str, Any]]:
    """Extract distinct sanitizer diagnostics from one run's stderr."""
    found: List[Dict[str, Any]] = []
    asan = _ASAN.search(stderr)
    if asan:
        found.append({"kind": "memory_error", "tool": "AddressSanitizer",
                      "message": asan.group(1), "line": _source_line(stderr, binary_path)})
    for match in _UBSAN.finditer(stderr):
        found.append({"kind": "undefined_behavior", "tool": "UndefinedBehaviorSanitizer",
                      "message": match.group(3).strip(), "line": int(match.group(1))})
    if "LeakSanitizer: detected memory leaks" in stderr:
        found.append({"kind": "leak", "tool": "LeakSanitizer",
                      "message": "memory leak detected", "line": None})
    return found


def defect_label(message: str) -> str:
    """Identify a defect, ignoring the addresses and values that vary between runs."""
    return _VOLATILE.sub("#", message.split(":")[0])


def parse_leak_marker(stderr: str) -> Optional[Tuple[int, int]]:
    found = _LEAK.findall(stderr)
    if not found:
        return None
    blocks, size = found[-1]
    return int(blocks), int(size)


@register
class SanitizerAnalyzer(Analyzer):
    name = "sanitizer_run"
    needs_execution = True
    PARAMS = {
        "flags": ((str, list), False),
        "testset_dir": (str, False),
        "extra_inputs": (list, False),
        "max_inputs": (int, False),
        "penalties": (dict, False),
        "check_leaks": (bool, False),
    }

    @classmethod
    def check_params(cls, params: Dict[str, Any]) -> List[str]:
        penalties = params.get("penalties", {})
        if not isinstance(penalties, dict):
            return []
        problems = [f"unknown penalty {key!r}" for key in penalties
                    if key not in _DEFAULT_PENALTIES]
        problems += [f"penalty {key!r} must be between 0 and 1" for key, value in penalties.items()
                     if isinstance(value, bool) or not isinstance(value, (int, float))
                     or not 0 <= value <= 1]
        return problems

    def run(self, context: AnalysisContext, params: Dict[str, Any]) -> AnalyzerResult:
        inputs = self._inputs(context, params)
        if not inputs:
            return AnalyzerResult.not_evaluated("no inputs are available to exercise the "
                                                "sanitized build")
        execution = context.rules.execution
        flags = split_flags(params.get("flags", "-fsanitize=address,undefined"))
        built = compile_source(context.backend, execution["compiler"], [context.source_file],
                               "sanitized.bin", flags + ["-g", "-O1", "-std=c11", "-w",
                                                         "-fno-omit-frame-pointer"],
                               context.workdir, execution["compile_timeout_s"],
                               execution["link_flags"])
        if not built.success:
            return AnalyzerResult.not_evaluated("the sanitizer build failed on this platform: "
                                                + built.output[:200])
        limits = Limits(time_s=max(context.rules.time_limit_s * 5, 5.0), memory_mb=None,
                        output_bytes=execution["max_output_bytes"],
                        max_processes=execution["max_processes"])
        binary_path = os.path.join(context.workdir, built.binary)
        diagnostics: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        for text in inputs:
            process = context.backend.run_binary(built.binary, limits, text.encode("utf-8"),
                                                 context.workdir, env=_SANITIZER_ENV)
            for item in parse_sanitizer_output(process.stderr, binary_path):
                key = (item["kind"], defect_label(item["message"]), item["line"])
                diagnostics.setdefault(key, dict(item, input=text))

        evidence: Dict[str, Any] = {"inputs_exercised": len(inputs), "flags": flags,
                                    "diagnostics": list(diagnostics.values())}
        skipped = []
        if params.get("check_leaks", True):
            leak, note = self._check_leaks(context, inputs, limits)
            if note:
                skipped.append({"tool": "allocation tracker", "reason": note})
            elif leak:
                blocks, size, text = leak
                evidence["not_freed_at_exit"] = {"blocks": blocks, "bytes": size}
                key = ("leak", "not freed", None)
                diagnostics[key] = {
                    "kind": "leak", "tool": "allocation tracker", "line": None, "input": text,
                    "message": f"{size} bytes in {blocks} block(s) not freed at exit"}
                evidence["diagnostics"] = list(diagnostics.values())
        return self._score(params, evidence, diagnostics, skipped)

    @staticmethod
    def _score(params: Dict[str, Any], evidence: Dict[str, Any],
               diagnostics: Dict[Tuple[Any, ...], Dict[str, Any]],
               skipped: List[Dict[str, str]]) -> AnalyzerResult:
        penalties = dict(_DEFAULT_PENALTIES, **params.get("penalties", {}))
        score = max(0.0, 1.0 - sum(penalties[item["kind"]] for item in diagnostics.values()))
        evidence["note"] = ("Absence of diagnostics covers only the exercised inputs and "
                            "does not prove memory safety.")
        if not diagnostics:
            return AnalyzerResult.scored(
                score, f"No diagnostics on {evidence['inputs_exercised']} exercised input(s).",
                evidence=evidence, skipped_tools=skipped)
        suggestions = []
        for item in diagnostics.values():
            where = f" at line {item['line']}" if item.get("line") else ""
            suggestions.append(f"{item['tool']} reported {item['message']}{where}.")
        return AnalyzerResult.scored(
            score, f"{len(diagnostics)} distinct memory or undefined-behaviour issue(s) found.",
            evidence=evidence, suggestions=suggestions, skipped_tools=skipped)

    @staticmethod
    def _inputs(context: AnalysisContext, params: Dict[str, Any]) -> List[str]:
        inputs = [str(item) for item in params.get("extra_inputs", [])]
        directory = params.get("testset_dir")
        path = context.rules.resolve(directory) if directory else context.rules.first_testset()
        if path:
            try:
                inputs += [case.input for case in load_testset(path) if not case.error]
            except FileNotFoundError:
                pass
        return inputs[:params.get("max_inputs", 25)]

    @staticmethod
    def _check_leaks(context: AnalysisContext, inputs: List[str], limits: Limits
                     ) -> Tuple[Optional[Tuple[int, int, str]], str]:
        backend: ExecutionBackend = context.backend
        execution = context.rules.execution
        shutil.copyfile(_RUNTIME, os.path.join(context.workdir, "leak_shim.c"))
        compiler, timeout = execution["compiler"], execution["compile_timeout_s"]
        runtime = compile_source(backend, compiler, ["leak_shim.c"], "leak_shim.o",
                                 ["-c", "-O1", "-w"], context.workdir, timeout)
        if not runtime.success:
            return None, "the allocation tracker did not compile"
        built = compile_source(backend, compiler, [context.source_file, "leak_shim.o"],
                               "tracked.bin", _LEAK_DEFINES + ["-O0", "-std=c11", "-w"],
                               context.workdir, timeout, execution["link_flags"])
        if not built.success:
            return None, "the tracked build failed: " + built.output[:200]
        for text in inputs:
            process = backend.run_binary(built.binary, limits, text.encode("utf-8"),
                                         context.workdir)
            marker = parse_leak_marker(process.stderr)
            if marker and marker[0] > 0:
                return (marker[0], marker[1], text), ""
        return None, ""
