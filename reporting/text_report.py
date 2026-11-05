"""Renders the student-facing report from the JSON report dict."""
from __future__ import annotations

from typing import Any, Dict, List

_RULE = "-" * 72


def _score_cell(metric: Dict[str, Any]) -> str:
    if metric["status"] == "scored":
        return f"{metric['contribution']:.1f}/{metric['max_contribution']:.1f}"
    if metric["status"] == "blocked":
        return f"0.0/{metric['max_contribution']:.1f}"
    return "n/a"


def _one_line(text: str) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= 70 else collapsed[:67] + "..."


def _show(text: Any) -> str:
    if text is None:
        return "(not known: no reference answer)"
    value = str(text).rstrip("\n")
    if not value:
        return "(empty)"
    return value.replace("\n", "\\n")


def _section_failures(report: Dict[str, Any]) -> List[str]:
    failures = report["feedback"]["where_you_failed"]
    if not failures:
        if report["scoring"]["zeroed_metrics"]:
            return ["The program did not get far enough to be tested on inputs."]
        return ["No failing input was found."]
    lines: List[str] = []
    for item in failures:
        label = "Test" if item["origin"] == "testset" else "Generated case"
        lines += [f"{label} {item['test_id']} [{item['outcome']}]",
                  f"  INPUT:    {_show(item['input'])}",
                  f"  EXPECTED: {_show(item['expected'])}",
                  f"  GOT:      {_show(item['got'])}",
                  f"  WHY:      {item['why']}", ""]
    return lines[:-1]


def _section_compilation(report: Dict[str, Any]) -> List[str]:
    compilation = report["compilation"]
    first = report["first_pass"]
    lines = [f"Compiled:  {'yes' if compilation['success'] else 'NO'} "
             f"({compilation['compiler_version']})",
             f"Flags:     {' '.join(compilation['flags'])}",
             f"Smoke run: {first['smoke_detail'] or 'not run'}"]
    if not compilation["success"] and compilation["output"]:
        lines += ["Compiler output:"] + [f"  {line}" for line in
                                         compilation["output"].splitlines()[:10]]
    sanity = first["static_sanity"]
    missing = [key for key, value in sanity.items() if not value]
    lines.append("Static sanity: " + ("all checks passed" if not missing
                                      else "not satisfied: " + ", ".join(missing)))
    return lines


def _section_tests(report: Dict[str, Any]) -> List[str]:
    for metric in report["metrics"]:
        results = metric["evidence"].get("results")
        if results is None:
            continue
        lines = [f"{metric['name']}: {metric['evidence']['tests_passed']} of "
                 f"{metric['evidence']['tests_total']} tests pass"]
        for result in results:
            duration = "" if result["duration_s"] is None else f"{result['duration_s']:.3f}s"
            lines.append(f"  {result['test_id']:<12} {result['status']:<12} {duration}")
        for item in metric["evidence"].get("malformed_tests", []):
            lines.append(f"  {item['test_id']:<12} not run: {item['problem']}")
        return lines
    return ["Test cases were not run."]


def _section_code_analysis(report: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    for metric in report["metrics"]:
        evidence = metric["evidence"]
        if metric["analyzer"] == "static_analysis":
            for item in evidence.get("cppcheck_findings", [])[:8]:
                lines.append(f"  cppcheck line {item['line']} [{item['severity']}]: "
                             f"{item['message']}")
        elif metric["analyzer"] == "compiler_warnings":
            for item in evidence.get("warnings", [])[:8]:
                lines.append(f"  compiler line {item['line']}: {item['message']}")
        elif metric["analyzer"] == "sanitizer_run":
            for item in evidence.get("diagnostics", [])[:8]:
                where = f" line {item['line']}" if item.get("line") else ""
                lines.append(f"  {item['tool']}{where}: {item['message']}")
            if evidence.get("note") and metric["status"] == "scored":
                lines.append(f"  Note: {evidence['note']}")
    return lines or ["  No findings."]


def _section_readability(report: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    for metric in report["metrics"]:
        evidence = metric["evidence"]
        if metric["analyzer"] == "llm_review" and "criteria" in evidence:
            lines.append("  Readability: " + ", ".join(
                f"{key} {value:.2f}" for key, value in evidence["criteria"].items()))
        elif metric["analyzer"] == "static_analysis":
            for item in evidence.get("functions", []):
                lines.append(f"  {item['name']}(): cyclomatic {item['cyclomatic']}, "
                             f"{item['length']} lines")
        elif metric["analyzer"] == "complexity_estimator" and "estimated" in evidence:
            pairs = ", ".join(f"n={size}: {count}" for size, count in
                              zip(evidence["sizes"], evidence["operation_counts"]))
            lines.append(f"  Growth: estimated {evidence['estimated']}, required "
                         f"{evidence['required']} (confidence {evidence['confidence']})")
            lines.append(f"  Operation counts: {pairs}")
    return lines or ["  Not available."]


def _section_similarity(report: Dict[str, Any]) -> List[str]:
    for metric in report["metrics"]:
        if metric["analyzer"] != "similarity_flag":
            continue
        if metric["status"] != "scored":
            return [f"  Not evaluated: {metric['feedback']}"]
        lines = [f"  {metric['feedback']}"]
        for match in metric["evidence"].get("top_matches", []):
            lines.append(f"  {match['target']} ({match['kind']}): similarity "
                         f"{match['jaccard']:.2f}, containment {match['containment']:.2f}")
        lines.append("  Similarity is a reason for review. It does not prove copying.")
        signals = metric["evidence"].get("style_signals_advisory")
        if signals:
            lines.append("  Advisory style hints (unscored): " + ", ".join(signals))
        return lines
    return ["  Not part of these rules."]


def _section_skipped(report: Dict[str, Any]) -> List[str]:
    lines = [f"  {item['check']} [{item['status']}]: {item['reason']}"
             for item in report["feedback"]["skipped_checks"]]
    execution = report["execution"]
    if not execution["isolated"]:
        lines.append("  WARNING: this submission ran WITHOUT isolation (unsafe backend).")
    excluded = report["scoring"]["excluded_metrics"]
    if excluded:
        lines.append(f"  Excluded from the grade: {', '.join(excluded)}")
    return lines or ["  None."]


def _section_suggestions(report: Dict[str, Any]) -> List[str]:
    suggestions = report["feedback"]["suggestions"]
    if not suggestions:
        return ["  None. Every check passed."]
    lines = []
    for item in suggestions[:12]:
        lines.append(f"  - [{item['metric']}] {item['text']}")
    remarks = report["feedback"]["advisory_llm_remarks"]
    if remarks:
        lines += ["", "  Advisory remarks from a local language model (unscored):"]
        lines += [f"  - {remark}" for remark in remarks]
    return lines


def _section_usefulness(report: Dict[str, Any]) -> List[str]:
    block = report.get("usefulness_limitations")
    if not block:
        return []
    lines = ["", _RULE, "Usefulness and limitations of this evaluation", _RULE, "Useful for:"]
    for number, item in enumerate(block["usefulness"], start=1):
        lines += [f"{number}. {item['use_case']}", f"   Example: {item['example']}",
                  f"   Benefit: {item['benefit']}"]
    lines.append("Limits of this report:")
    for number, item in enumerate(block["limitations"], start=1):
        lines += [f"{number}. {item['limitation']}", f"   Example: {item['example']}",
                  f"   Fix: {item['mitigation']}"]
    return lines


def _grade_line(report: Dict[str, Any]) -> str:
    grade = report["grade"]
    if grade is None:
        return "Overall grade: NOT GRADABLE (no metric could be evaluated)"
    return f"Overall grade: {grade:.2f} / 100"


def render_text(report: Dict[str, Any]) -> str:
    scoring = report["scoring"]
    lines = [f"===== Grading report for {report['submission']} =====",
             f"Problem:  {report['problem']}",
             f"Rules:    {report['rules_file']} ({report['rules_hash'][:19]}...)",
             f"Source:   {report['source_hash'][:19]}...",
             f"Run at:   {report['timestamp']}",
             f"Sandbox:  {report['execution']['name']}",
             "",
             _grade_line(report),
             f"Status:   {report['evaluation_status']}",
             ""]
    for flag in report["flags"]:
        if flag["type"] == "suspected_copying":
            lines.append(f"FLAG: suspected_copying, {flag['similarity']:.2f} similar to "
                         f"{flag['target']} ({flag['source_kind']}). {flag['note']}")
        elif flag["type"] != "style_signals_advisory":
            lines.append(f"FLAG: {flag['type']}")
    if report["flags"]:
        lines.append("")

    lines += [f"{'Metric':<16}{'Weight':>7}{'Marks':>13}  Verdict", _RULE]
    for metric in report["metrics"]:
        lines.append(f"{metric['name']:<16}{metric['weight'] * 100:>6.0f}%"
                     f"{_score_cell(metric):>13}  {_one_line(metric['feedback'])}")
    lines += [_RULE, f"Formula: {scoring['formula']}",
              f"Applicable weight: {scoring['applicable_weight']:g} of "
              f"{scoring['total_weight']:g}", ""]

    sections = [
        ("Compilation", _section_compilation(report)),
        ("Test cases", _section_tests(report)),
        ("Where you failed", _section_failures(report)),
        ("Code analysis findings", _section_code_analysis(report)),
        ("Readability and complexity", _section_readability(report)),
        ("Similarity", _section_similarity(report)),
        ("Skipped checks and limitations", _section_skipped(report)),
        ("Suggestions to raise the grade", _section_suggestions(report)),
    ]
    for title, body in sections:
        lines += [f"--- {title} ---"] + body + [""]
    lines += _section_usefulness(report)
    return "\n".join(lines).rstrip() + "\n"


def write_text(report: Dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(render_text(report))
