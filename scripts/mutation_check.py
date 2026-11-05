#!/usr/bin/env python3
"""Deliberately breaks critical logic and confirms the test suite notices.

Each mutant applies one source change, runs the relevant tests, then restores the
file. A mutant that survives means those tests prove less than they appear to.
"""
import pathlib
import subprocess
import sys

MUTANTS = [
    ("scoring/score_calculator.py", 'metric.contribution = round(100.0 * metric.weight * score / denominator, 4)',
     'metric.contribution = round(100.0 * metric.weight / denominator, 4)', "tests/test_scoring.py", "contribution ignores score"),
    ("scoring/score_calculator.py", 'elif status == MetricStatus.NOT_EVALUATED and unavailable == "renormalize":',
     'elif status in (MetricStatus.NOT_EVALUATED, MetricStatus.BLOCKED):', "tests/test_scoring.py", "blocked metrics excused from the grade"),
    ("scoring/score_calculator.py", 'if denominator <= 0:', 'if False:', "tests/test_scoring.py", "division by zero guard removed"),
    ("agent/coordinator.py", 'if first.suspected_infinite_loop:\n        return "skipped', 'if False:\n        return "skipped', "tests/test_end_to_end.py", "hang no longer skips execution analyzers"),
    ("analyzers/correctness.py", 'nonzero = require_zero_exit and process.exit_code != 0', 'nonzero = False', "tests/test_analyzers_exec.py", "exit status ignored"),
    ("analyzers/testset.py", 'if expected == actual:\n        return True, ""\n    if mode == "exact":\n        return False, ""', 'if expected == actual:\n        return True, ""', "tests/test_analyzers_exec.py", "exact comparison made lenient"),
    ("analyzers/originality.py", 'normalized.append(token.text if keep else "ID")', 'normalized.append(token.text)', "tests/test_analyzers_source.py", "renaming defeats similarity"),
    ("analyzers/originality.py", 'if name.endswith(".c") and os.path.realpath(path) != own_path:', 'if name.endswith(".c"):', "tests/test_analyzers_source.py", "submission matches itself"),
    ("analyzers/complexity.py", '"-O0", "-std=c11", "-w", "-fsanitize-coverage=trace-pc"', '"-O0", "-std=c11", "-w"', "tests/test_analyzers_exec.py", "operation counters not compiled in"),
    ("analyzers/explain.py", 'if gap and gap % _TWO_32 == 0:', 'if False:', "tests/test_explain.py", "overflow explanation removed"),
    ("execution/process_runner.py", 'if time.monotonic() - started > wall_limit or (\n                    judge_cpu and cpu_seconds > limits.time_s):', 'if False:', "tests/test_process_runner.py", "timeouts removed"),
    ("execution/process_runner.py", 'wall_limit = limits.time_s * WALL_BACKSTOP_FACTOR if judge_cpu else limits.time_s', 'wall_limit = limits.time_s', "tests/test_process_runner.py", "time limit judged by elapsed time again"),
    ("execution/process_runner.py", 'if memory_limit_bytes is not None and footprint > memory_limit_bytes:', 'if False:', "tests/test_process_runner.py", "memory limit removed"),
    ("execution/sandbox.py", '(allow process-exec (literal (param "BINARY")))', '(allow process-exec*)\n(allow process-fork)', "tests/test_sandbox.py", "sandbox allows fork and exec"),
    ("execution/sandbox.py", '(allow file-write* (literal "/dev/null"))\n(allow sysctl-read)\n(allow mach-lookup (global', '(allow file-write*)\n(allow sysctl-read)\n(allow mach-lookup (global', "tests/test_sandbox.py", "sandbox allows file writes"),
    ("execution/sandbox.py", '(subpath "/Library/Developer") (subpath (param "WORK")))\n(allow file-write* (literal "/dev/null"))\n(allow sysctl-read)\n(allow mach-lookup (global', '(subpath "/Library/Developer") (subpath (param "WORK")) (subpath "/Users"))\n(allow file-write* (literal "/dev/null"))\n(allow sysctl-read)\n(allow mach-lookup (global', "tests/test_sandbox.py", "sandbox allows reading /Users"),
    ("execution/sandbox.py", 'if preference == "unsafe" or allow_unsafe:\n        if not allow_unsafe:', 'if preference == "unsafe" or allow_unsafe:\n        if False:', "tests/test_sandbox.py", "unsafe backend without opt-in"),
    ("reporting/json_report.py", '"grade": summary.grade,', '"grade": summary.grade and summary.grade + 1,', "tests/test_reports.py", "JSON grade drifts from contributions"),
    ("agent/config_loader.py", 'elif weight < 0:', 'elif False:', "tests/test_config.py", "negative weights accepted"),
    ("web/server.py", 'if self.headers.get("Host") not in allowed or (', 'if False and (', "tests/test_web.py", "web server accepts foreign requests"),
    ("web/server.py", 'rules_path = _rules_paths().get(payload.get("rules"))', 'rules_path = payload.get("rules")', "tests/test_web.py", "web rule set accepts any path"),
    ("analyzers/memory_safety.py", 'return _VOLATILE.sub("#", message.split(":")[0])', 'return message', "tests/test_analyzers_exec.py", "same defect counted per input"),
]
root = pathlib.Path(__file__).resolve().parent.parent
survived = []
only = sys.argv[1] if len(sys.argv) > 1 else ""
selected = [mutant for mutant in MUTANTS if only in mutant[4]]
for path, old, new, tests, label in selected:
    target = root / path
    original = target.read_text()
    if original.count(old) < 1:
        print(f"STALE    {label}: pattern not found in {path}")
        survived.append(label)
        continue
    target.write_text(original.replace(old, new, 1))
    try:
        done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", tests, "-p", "no:cacheprovider"],
                              cwd=root, capture_output=True, text=True, timeout=400)
    finally:
        target.write_text(original)
    killed = done.returncode != 0
    print(f"{'killed  ' if killed else 'SURVIVED'} {label}", flush=True)
    if not killed:
        survived.append(label)
print(f"\n{len(selected) - len(survived)} of {len(selected)} mutants killed")
sys.exit(1 if survived else 0)
