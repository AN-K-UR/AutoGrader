"""``io_tests``: runs the instructor's tests and compares outputs."""
from __future__ import annotations

from typing import Any, Dict, List

from analyzers.base import AnalysisContext, Analyzer, register
from analyzers.explain import explain_test, run_binary, run_outcome_status
from analyzers.testset import (COMPARISONS, TestCase, compare_output, load_testset,
                               parameter_time, summarize_statuses)
from execution.process_runner import Limits
from models.results import AnalyzerResult, Counterexample, TestCaseResult, to_plain


def execute_test(context: AnalysisContext, case: TestCase, comparison: str,
                 require_zero_exit: bool) -> TestCaseResult:
    """Run one test case and classify the result. Never raises for student bugs."""
    rules = context.rules
    limits = Limits(time_s=parameter_time(case.time_limit_s, rules.time_limit_s),
                    memory_mb=rules.memory_limit_mb,
                    output_bytes=rules.execution["max_output_bytes"],
                    max_processes=rules.execution["max_processes"])
    process = run_binary(context.backend, context.workdir, context.binary, limits, case.input)
    mode = case.comparison or comparison
    result = TestCaseResult(
        test_id=case.test_id, status="failed", description=case.description,
        input=case.input, expected=case.expected, actual=process.stdout,
        stderr=process.stderr, exit_code=process.exit_code, duration_s=process.duration_s,
        peak_memory_kb=process.peak_memory_kb, comparison=mode,
    )
    state = run_outcome_status(process)
    if state != "completed":
        result.status = state
    else:
        matches, note = compare_output(case.expected or "", process.stdout, mode)
        result.diagnostic = note
        nonzero = require_zero_exit and process.exit_code != 0
        result.status = "passed" if matches and not nonzero else "failed"
    if not result.passed:
        result.diagnostic = explain_test(result, process, limits)
    return result


@register
class IOTestsAnalyzer(Analyzer):
    name = "io_tests"
    needs_execution = True
    PARAMS = {
        "testset_dir": (str, True),
        "comparison": (str, False),
        "require_zero_exit": (bool, False),
    }

    @classmethod
    def check_params(cls, params: Dict[str, Any]) -> List[str]:
        mode = params.get("comparison", "trim_trailing")
        return [] if mode in COMPARISONS else [
            f"comparison must be one of {', '.join(COMPARISONS)}, got {mode!r}"]

    def run(self, context: AnalysisContext, params: Dict[str, Any]) -> AnalyzerResult:
        directory = context.rules.resolve(params["testset_dir"])
        try:
            cases = load_testset(directory)
        except FileNotFoundError as error:
            return AnalyzerResult.not_evaluated(str(error))
        if not cases:
            return AnalyzerResult.not_evaluated("the test directory contains no test cases")

        comparison = params.get("comparison", "trim_trailing")
        require_zero_exit = params.get("require_zero_exit", True)
        malformed = [{"test_id": case.test_id, "problem": case.error}
                     for case in cases if case.error]
        runnable = [case for case in cases if not case.error]
        if not runnable:
            return AnalyzerResult.not_evaluated("every test case is malformed",
                                                evidence={"malformed_tests": malformed})

        results = [execute_test(context, case, comparison, require_zero_exit)
                   for case in runnable]
        passed = sum(1 for result in results if result.passed)
        counterexamples = [
            Counterexample(test_id=result.test_id, input=result.input,
                           expected=result.expected, got=result.actual,
                           why=result.diagnostic, origin="testset", outcome=result.status)
            for result in results if not result.passed
        ]
        evidence: Dict[str, Any] = {
            "tests_passed": passed,
            "tests_total": len(results),
            "comparison": comparison,
            "status_counts": summarize_statuses([result.status for result in results]),
            "results": [to_plain(result) for result in results],
        }
        feedback = f"{passed} of {len(results)} tests pass."
        if malformed:
            # Excluded from the score: an instructor's broken test is not the
            # student's fault, and it is never counted as a pass either.
            evidence["malformed_tests"] = malformed
            feedback += f" {len(malformed)} malformed test(s) were not run."
        suggestions = []
        if counterexamples:
            first = counterexamples[0]
            suggestions.append(f"Fix the failure on test {first.test_id}: {first.why}")
        return AnalyzerResult.scored(passed / len(results), feedback, evidence=evidence,
                                     counterexamples=counterexamples, suggestions=suggestions)
