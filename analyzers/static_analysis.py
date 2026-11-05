"""``static_analysis``: Cppcheck findings plus Lizard function metrics.

Either tool may be missing. Whatever ran is scored, the missing tool is recorded
as skipped, and if neither ran the metric is ``not_evaluated``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from typing import Any, Dict, List, Optional, Tuple

from analyzers.base import AnalysisContext, Analyzer, register
from models.results import AnalyzerResult, Diagnostic, to_plain

_CPPCHECK_TIMEOUT_S = 30
_DEFAULT_SEVERITY = {"error": 0.3, "warning": 0.15, "style": 0.05, "performance": 0.05,
                     "portability": 0.05, "information": 0.0}
_MAX_CPPCHECK_PENALTY = 0.8
_THRESHOLD_PENALTY = 0.2


def find_tool(name: str) -> Optional[str]:
    """Look on PATH, then beside this interpreter so an unactivated venv works."""
    return shutil.which(name) or shutil.which(name, path=os.path.dirname(sys.executable))


def parse_cppcheck_xml(xml_text: str) -> List[Diagnostic]:
    """Parse ``--xml --xml-version=2`` output, ignoring anything not an error node."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    findings = []
    for error in root.iter("error"):
        if error.get("id") in ("checkersReport", "normalCheckLevelMaxBranches"):
            continue
        location = error.find("location")
        line = location.get("line") if location is not None else None
        findings.append(Diagnostic(tool="cppcheck", severity=error.get("severity", "style"),
                                   message=error.get("msg", ""), code=error.get("id"),
                                   line=int(line) if line else None))
    return findings


def run_cppcheck(path: str, standard: str = "c11") -> Tuple[Optional[List[Diagnostic]], str]:
    """Run Cppcheck on one file. Returns (findings or None, version or reason)."""
    binary = find_tool("cppcheck")
    if binary is None:
        return None, "cppcheck is not installed"
    argv = [binary, "--xml", "--xml-version=2", "--language=c", f"--std={standard}",
            "--enable=warning,style,performance,portability",
            "--suppress=missingIncludeSystem", "--suppress=checkersReport", "--quiet", path]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                              timeout=_CPPCHECK_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        return None, f"cppcheck exceeded {_CPPCHECK_TIMEOUT_S} s"
    except OSError as error:
        return None, f"cppcheck failed to start: {error}"
    if "<results" not in done.stderr:
        return None, "cppcheck produced no XML output: " + done.stderr[:200]
    return parse_cppcheck_xml(done.stderr), ""


def run_lizard(name: str, code: str) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """Collect per-function metrics from Lizard's Python API."""
    try:
        import lizard
    except ImportError:
        return None, "lizard is not installed"
    analysis = lizard.analyze_file.analyze_source_code(name, code)
    return [{"name": item.name, "cyclomatic": item.cyclomatic_complexity,
             "length": item.nloc, "tokens": item.token_count,
             "parameters": item.parameter_count, "line": item.start_line}
            for item in analysis.function_list], ""


@register
class StaticAnalysisAnalyzer(Analyzer):
    name = "static_analysis"
    PARAMS = {
        "max_cyclomatic": (int, False),
        "max_function_length": (int, False),
        "severity_penalties": (dict, False),
    }

    @classmethod
    def check_params(cls, params: Dict[str, Any]) -> List[str]:
        mapping = params.get("severity_penalties", {})
        if not isinstance(mapping, dict):
            return []
        return [f"severity_penalties[{key!r}] must be between 0 and 1"
                for key, value in mapping.items()
                if isinstance(value, bool) or not isinstance(value, (int, float))
                or not 0 <= value <= 1]

    def run(self, context: AnalysisContext, params: Dict[str, Any]) -> AnalyzerResult:
        path = os.path.join(context.workdir, context.source_file)
        findings, cppcheck_note = run_cppcheck(path)
        functions, lizard_note = run_lizard(context.source_file, context.source.text)
        skipped = []
        if findings is None:
            skipped.append({"tool": "cppcheck", "reason": cppcheck_note})
        if functions is None:
            skipped.append({"tool": "lizard", "reason": lizard_note})
        if findings is None and functions is None:
            return AnalyzerResult.not_evaluated("neither cppcheck nor lizard is available",
                                                skipped_tools=skipped)

        components: List[float] = []
        evidence: Dict[str, Any] = {}
        suggestions: List[str] = []
        summary: List[str] = []
        if findings is not None:
            penalties = dict(_DEFAULT_SEVERITY, **params.get("severity_penalties", {}))
            lost = sum(penalties.get(item.severity, 0.05) for item in findings)
            components.append(1.0 - min(lost, _MAX_CPPCHECK_PENALTY))
            evidence["cppcheck_findings"] = to_plain(findings)
            summary.append(f"{len(findings)} cppcheck finding(s)")
            suggestions += [f"Line {item.line}: {item.message} ({item.code})"
                            for item in findings[:5]]
        if functions is not None:
            max_cyclomatic = params.get("max_cyclomatic", 10)
            max_length = params.get("max_function_length", 60)
            over = [item for item in functions if item["cyclomatic"] > max_cyclomatic
                    or item["length"] > max_length]
            components.append(max(0.0, 1.0 - _THRESHOLD_PENALTY * len(over)))
            evidence["functions"] = functions
            evidence["thresholds"] = {"max_cyclomatic": max_cyclomatic,
                                      "max_function_length": max_length}
            summary.append(f"{len(over)} function(s) over thresholds")
            for item in over:
                suggestions.append(
                    f"Function {item['name']} (line {item['line']}) has cyclomatic complexity "
                    f"{item['cyclomatic']} and {item['length']} lines; the limits are "
                    f"{max_cyclomatic} and {max_length}. Split it into smaller functions.")
        return AnalyzerResult.scored(sum(components) / len(components), "; ".join(summary) + ".",
                                     evidence=evidence, suggestions=suggestions,
                                     skipped_tools=skipped)
