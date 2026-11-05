"""``edge_case_runner``: generates corner cases and tests them differentially.

The assignment asks the agent to find its own counter test cases. Inputs come from
a seeded generator driven by the rule's ``input_spec``. The instructor's reference
solution supplies the expected answer. Without a reference, only crashes, hangs and
limit violations can be detected, and the evidence says so.
"""
from __future__ import annotations

import os
import random
import shutil
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from analyzers.base import AnalysisContext, Analyzer, register
from analyzers.explain import explain_test, run_binary, run_outcome_status
from analyzers.testset import COMPARISONS, compare_output
from execution.compiler import compile_source, split_flags
from execution.process_runner import Limits
from models.results import AnalyzerResult, Counterexample, ProcessResult, TestCaseResult

INT_MAX = 2 ** 31 - 1
INT_MIN = -2 ** 31

_INT_CATEGORIES = ("negatives", "zero", "int_overflow", "int_boundaries", "whitespace",
                   "empty_input", "random")
_ARRAY_CATEGORIES = ("empty_array", "single_element", "duplicates", "already_sorted",
                     "reverse_sorted", "negatives", "extreme_values", "whitespace", "random")


@dataclass
class EdgeCase:
    case_id: str
    category: str
    input: str


def _pairs(values: List[Tuple[int, ...]]) -> List[str]:
    return [" ".join(str(value) for value in row) + "\n" for row in values]


def _int_inputs(category: str, count: int, generator: random.Random,
                random_cases: int) -> List[str]:
    def row(*values: int) -> Tuple[int, ...]:
        padded = (list(values) * count)[:count]
        return tuple(padded)

    if category == "negatives":
        return _pairs([row(-1, -2), row(-7, 5), row(9, -9), row(-1000, -1)])
    if category == "zero":
        return _pairs([row(0, 0), row(0, 5), row(5, 0), row(0, -5)])
    if category == "int_overflow":
        return _pairs([row(INT_MAX, 1), row(INT_MIN, -1), row(INT_MAX, INT_MAX),
                       row(INT_MIN, INT_MIN)])
    if category == "int_boundaries":
        return _pairs([row(INT_MAX, 0), row(INT_MIN, 0), row(INT_MAX, INT_MIN),
                       row(INT_MAX - 1, 1)])
    if category == "whitespace":
        separators = ("  ", "\t", "\n", "\n\n  ")
        values = [str(generator.randint(1, 99)) for _ in range(count)]
        return [sep.join(values) + "\n" for sep in separators] + [
            "  " + " ".join(values) + "  \n", " ".join(values)]
    if category == "empty_input":
        return ["", "\n"]
    return _pairs([tuple(generator.randint(-10 ** 6, 10 ** 6) for _ in range(count))
                   for _ in range(random_cases)])


def _array_input(values: List[int], separator: str = " ") -> str:
    return f"{len(values)}\n{separator.join(str(value) for value in values)}\n"


def _array_inputs(category: str, generator: random.Random, random_cases: int) -> List[str]:
    def numbers(size: int, low: int = -1000, high: int = 1000) -> List[int]:
        return [generator.randint(low, high) for _ in range(size)]

    if category == "empty_array":
        return ["0\n\n"]
    if category == "single_element":
        return [_array_input([5]), _array_input([-5]), _array_input([0])]
    if category == "duplicates":
        return [_array_input([3, 3, 3, 3]), _array_input([2, 1, 2, 1, 2])]
    if category == "already_sorted":
        return [_array_input(list(range(1, 21)))]
    if category == "reverse_sorted":
        return [_array_input(list(range(20, 0, -1)))]
    if category == "negatives":
        return [_array_input([-1, -5, -3]), _array_input([0, -1, 1])]
    if category == "extreme_values":
        return [_array_input([INT_MAX, INT_MIN, 0]), _array_input([INT_MAX, INT_MAX - 1]),
                _array_input([INT_MIN, INT_MAX, INT_MIN])]
    if category == "whitespace":
        return ["3\n1\n2\n3\n", "  3  \n 3   1\t2 \n"]
    return [_array_input(numbers(generator.randint(2, 40))) for _ in range(random_cases)]


def generate_cases(spec: Dict[str, Any], categories: List[str], seed: int,
                   random_cases: int) -> List[EdgeCase]:
    """Deterministically generate cases: same spec and seed, same cases."""
    generator = random.Random(seed)
    kind = spec.get("kind", "ints")
    known = _ARRAY_CATEGORIES if kind == "array" else _INT_CATEGORIES
    chosen = list(known) if categories == ["all"] else categories
    cases: List[EdgeCase] = []
    for category in chosen:
        if category not in known:
            continue
        if kind == "array":
            inputs = _array_inputs(category, generator, random_cases)
        else:
            inputs = _int_inputs(category, spec.get("count", 2), generator, random_cases)
        for index, text in enumerate(inputs, start=1):
            cases.append(EdgeCase(f"{category}-{index}", category, text))
    return cases


def _prepare_reference(context: AnalysisContext, path: str) -> Tuple[Optional[str], str]:
    """Compile the reference once per evaluation."""
    cached = context.shared.get(("reference", path))
    if cached:
        return cached, ""
    if not os.path.isfile(path):
        return None, f"reference solution not found: {os.path.basename(path)}"
    shutil.copyfile(path, os.path.join(context.workdir, "reference.c"))
    execution = context.rules.execution
    built = compile_source(context.backend, execution["compiler"], ["reference.c"],
                           "reference.bin",
                           split_flags(context.rules.first_pass["compile_flags"]),
                           context.workdir, execution["compile_timeout_s"],
                           execution["link_flags"])
    if not built.success:
        return None, "reference solution does not compile"
    context.shared[("reference", path)] = built.binary
    return built.binary, ""


@register
class EdgeCaseAnalyzer(Analyzer):
    name = "edge_case_runner"
    needs_execution = True
    PARAMS = {
        "cases": (list, True),
        "input_spec": (dict, False),
        "reference_solution": (str, False),
        "seed": (int, False),
        "random_cases": (int, False),
        "comparison": (str, False),
    }

    @classmethod
    def check_params(cls, params: Dict[str, Any]) -> List[str]:
        spec = params.get("input_spec", {})
        kind = spec.get("kind", "ints") if isinstance(spec, dict) else "ints"
        problems: List[str] = []
        if kind not in ("ints", "array"):
            return [f"input_spec.kind must be ints or array, got {kind!r}"]
        known = _ARRAY_CATEGORIES if kind == "array" else _INT_CATEGORIES
        cases = params.get("cases", [])
        if isinstance(cases, list) and cases != ["all"]:
            for category in cases:
                if category not in known:
                    problems.append(f"unknown case category {category!r} for kind {kind}; "
                                    f"known: {', '.join(known)}")
        if params.get("comparison", "trim_trailing") not in COMPARISONS:
            problems.append(f"comparison must be one of {', '.join(COMPARISONS)}")
        return problems

    def run(self, context: AnalysisContext, params: Dict[str, Any]) -> AnalyzerResult:
        reference_path = params.get("reference_solution")
        reference = None
        if reference_path:
            reference, problem = _prepare_reference(context,
                                                    context.rules.resolve(reference_path))
            if reference is None:
                return AnalyzerResult.not_evaluated(problem)

        cases = generate_cases(params.get("input_spec", {}), params["cases"],
                               params.get("seed", 42), params.get("random_cases", 5))
        if not cases:
            return AnalyzerResult.not_evaluated("no edge cases were generated")

        rules = context.rules
        limits = Limits(time_s=rules.time_limit_s, memory_mb=rules.memory_limit_mb,
                        output_bytes=rules.execution["max_output_bytes"],
                        max_processes=rules.execution["max_processes"])
        comparison = params.get("comparison", "trim_trailing")
        failures: List[Counterexample] = []
        evaluated, passed = 0, 0
        unusable: List[str] = []
        by_category: Dict[str, Dict[str, int]] = {}
        for case in cases:
            expected = None
            if reference:
                oracle = run_binary(context.backend, context.workdir, reference, limits,
                                    case.input)
                if not oracle.clean_exit:
                    # The reference rejects this input, so it says nothing about
                    # correct behaviour and must not count against the student.
                    unusable.append(case.case_id)
                    continue
                expected = oracle.stdout
            process = run_binary(context.backend, context.workdir, context.binary, limits,
                                 case.input)
            evaluated += 1
            tally = by_category.setdefault(case.category, {"passed": 0, "total": 0})
            tally["total"] += 1
            failure = self._judge(case, expected, process, comparison, limits)
            if failure is None:
                passed += 1
                tally["passed"] += 1
            else:
                failures.append(failure)

        if evaluated == 0:
            return AnalyzerResult.not_evaluated("the reference rejected every generated input")
        failures.sort(key=lambda item: (len(item.input), item.test_id))
        evidence = {
            "cases_passed": passed,
            "cases_total": evaluated,
            "by_category": by_category,
            "seed": params.get("seed", 42),
            "oracle": "reference_solution" if reference else
                      "none: only crashes, timeouts and limit violations are detectable",
            "unusable_cases": unusable,
        }
        feedback = f"{passed} of {evaluated} generated corner cases pass."
        suggestions = []
        if failures:
            worst = sorted({failure.category or "" for failure in failures})
            feedback += f" Failing categories: {', '.join(worst)}."
            suggestions.append(f"Handle the {worst[0].replace('_', ' ')} case: "
                               f"{failures[0].why}")
        return AnalyzerResult.scored(passed / evaluated, feedback, evidence=evidence,
                                     counterexamples=failures, suggestions=suggestions)

    @staticmethod
    def _judge(case: EdgeCase, expected: Optional[str], process: ProcessResult,
               comparison: str, limits: Limits) -> Optional[Counterexample]:
        state = run_outcome_status(process)
        if state == "completed":
            if expected is None:
                return None
            matches = compare_output(expected, process.stdout, comparison)[0]
            if matches and process.exit_code == 0:
                return None
            state = "failed"
        record = TestCaseResult(test_id=case.case_id, status=state, input=case.input,
                                expected=expected, actual=process.stdout,
                                exit_code=process.exit_code)
        return Counterexample(test_id=case.case_id, input=case.input, expected=expected,
                              got=process.stdout,
                              why=explain_test(record, process, limits, case.category),
                              origin="generated", category=case.category, outcome=state)
