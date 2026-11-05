"""Turns a failed run into a specific explanation.

Each explanation is derived by comparing the actual expected/got pair, so the
text can be traced to the evidence. No language model is involved.
"""
from __future__ import annotations

import re
from typing import List, Optional

from execution.process_runner import Limits, describe_signal
from execution.sandbox import ExecutionBackend
from models.results import ProcessResult, RunOutcome, TestCaseResult

_TWO_32 = 2 ** 32
_INT = re.compile(r"^-?\d+$")

CATEGORY_HINTS = {
    "int_overflow": "The input sits at the limit of a 32-bit int, so the arithmetic can "
                    "overflow. Use long long, or check for overflow before the operation.",
    "int_boundaries": "The input uses INT_MIN or INT_MAX. Check every intermediate value "
                      "and any negation or absolute value.",
    "negatives": "The input is negative. Check for signed arithmetic and for conditions "
                 "that assume positive values.",
    "zero": "The input includes zero. Check division, loop bounds, and special cases.",
    "whitespace": "The numbers are separated by unusual whitespace. Read with scanf or "
                  "another reader that skips whitespace, not with a fixed line layout.",
    "empty_array": "The array is empty. Make sure no element is read and no loop runs.",
    "single_element": "The array has one element. Check loop bounds, which are often off "
                      "by one here.",
    "duplicates": "The input has repeated values. Check comparisons that assume every "
                  "value is distinct.",
    "already_sorted": "The input is already sorted, a classic worst case or early-exit bug.",
    "reverse_sorted": "The input is in reverse order, which often exposes loop-bound bugs.",
    "extreme_values": "The input has very large magnitudes. Comparisons by subtraction "
                      "overflow; compare with < and > instead.",
    "empty_input": "There is no input at all. Check the return value of scanf.",
    "random": "A random valid input. Trace your program by hand on this input.",
}


def run_outcome_status(process: ProcessResult) -> str:
    """Map a process outcome onto a test status."""
    return {
        RunOutcome.TIMEOUT: "timeout",
        RunOutcome.MEMORY_LIMIT: "memory_limit",
        RunOutcome.OUTPUT_LIMIT: "output_limit",
        RunOutcome.SIGNALED: "crashed",
        RunOutcome.FAILED_TO_START: "crashed",
    }.get(process.outcome, "completed")


def explain_process_failure(process: ProcessResult, limits: Limits) -> str:
    if process.outcome == RunOutcome.TIMEOUT:
        return (f"The program did not finish within {limits.time_s:g} s. Look for a loop "
                "whose exit condition is never reached, or an algorithm that is too slow.")
    if process.outcome == RunOutcome.MEMORY_LIMIT:
        return (f"The program used more than the {limits.memory_mb} MB memory limit. Look "
                "for unbounded allocation or runaway recursion.")
    if process.outcome == RunOutcome.OUTPUT_LIMIT:
        return "The program produced too much output, usually a print inside a runaway loop."
    if process.outcome == RunOutcome.SIGNALED:
        name = describe_signal(process.signal)
        hints = {"SIGSEGV": "invalid memory access, such as a null or out-of-bounds pointer, "
                            "or very deep recursion",
                 "SIGBUS": "invalid memory access",
                 "SIGFPE": "an arithmetic fault, such as integer division by zero",
                 "SIGABRT": "abort() or a failed assert or heap check"}
        detail = hints.get(name)
        return f"The program crashed with {name}" + (f": {detail}." if detail else ".")
    if process.outcome == RunOutcome.FAILED_TO_START:
        return f"The program could not be started: {process.error}"
    return f"The program exited with status {process.exit_code} instead of 0."


def explain_difference(expected: str, actual: str) -> str:
    """Describe how the output differs from the expected output."""
    if not actual.strip():
        return "The program printed nothing, but output was expected."
    if expected.split() == actual.split():
        return ("The values are right but the layout differs: "
                + _layout_difference(expected, actual))
    numeric = _numeric_difference(expected.strip(), actual.strip())
    if numeric:
        return numeric
    want, got = expected.splitlines(), actual.splitlines()
    if len(want) != len(got):
        return (f"Printed {len(got)} line(s) but {len(want)} expected; "
                + _first_mismatch(want, got))
    return _first_mismatch(want, got)


def _layout_difference(expected: str, actual: str) -> str:
    if expected.rstrip("\n") == actual.rstrip("\n"):
        return "the final newline is different."
    return "spacing or line breaks are different."


def _numeric_difference(expected: str, actual: str) -> Optional[str]:
    if not (_INT.match(expected) and _INT.match(actual)):
        return None
    want, got = int(expected), int(actual)
    gap = abs(want - got)
    if gap and gap % _TWO_32 == 0:
        return (f"Printed {got}, expected {want}. They differ by a multiple of 2^32, the "
                "signature of 32-bit integer overflow. Use a wider type such as long long.")
    if gap == 1:
        return f"Off by one: printed {got}, expected {want}. Check boundaries and < versus <=."
    if want == -got:
        return f"Wrong sign: printed {got}, expected {want}."
    return f"Printed {got}, expected {want}."


def _first_mismatch(want: List[str], got: List[str]) -> str:
    for number, (left, right) in enumerate(zip(want, got), start=1):
        if left != right:
            return f"First difference is on line {number}: expected {left!r}, got {right!r}."
    return "The output is a prefix of the other; lines are missing or extra at the end."


def explain_test(result: TestCaseResult, process: Optional[ProcessResult], limits: Limits,
                 category: Optional[str] = None) -> str:
    """Full explanation for a failed test, adding the category hint when known."""
    if process is not None and result.status != "failed":
        text = explain_process_failure(process, limits)
    elif process is not None and process.exit_code not in (0, None):
        text = explain_process_failure(process, limits)
    else:
        text = explain_difference(result.expected or "", result.actual)
    hint = CATEGORY_HINTS.get(category or "")
    return f"{text} {hint}" if hint else text


def run_binary(context_backend: ExecutionBackend, workdir: str, binary: str, limits: Limits,
               stdin_text: str) -> ProcessResult:
    return context_backend.run_binary(binary, limits, stdin_text.encode("utf-8"), workdir)
