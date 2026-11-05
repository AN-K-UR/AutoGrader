from analyzers.explain import explain_difference, explain_process_failure
from execution.process_runner import Limits
from models.results import ProcessResult, RunOutcome
import signal

LIMITS = Limits(time_s=1, memory_mb=64)


def test_empty_output():
    assert "printed nothing" in explain_difference("12\n", "")


def test_overflow_signature_beats_wrong_sign():
    text = explain_difference("2147483648\n", "-2147483648\n")
    assert "2^32" in text and "long long" in text


def test_off_by_one():
    assert "Off by one" in explain_difference("10\n", "11\n")


def test_wrong_sign():
    assert "Wrong sign" in explain_difference("5\n", "-5\n")


def test_layout_only():
    assert "layout differs" in explain_difference("1 2\n", "1\n2\n")
    assert "final newline" in explain_difference("1\n", "1")


def test_first_differing_line_named():
    assert "line 2" in explain_difference("a\nb\nc\n", "a\nx\nc\n")


def test_line_count_mismatch():
    assert "Printed 1 line(s) but 2 expected" in explain_difference("a\nb\n", "a\n")


def test_process_failures():
    timeout = ProcessResult(outcome=RunOutcome.TIMEOUT)
    assert "did not finish within 1 s" in explain_process_failure(timeout, LIMITS)
    memory = ProcessResult(outcome=RunOutcome.MEMORY_LIMIT)
    assert "64 MB" in explain_process_failure(memory, LIMITS)
    crash = ProcessResult(outcome=RunOutcome.SIGNALED, signal=int(signal.SIGSEGV))
    assert "SIGSEGV" in explain_process_failure(crash, LIMITS)
    divide = ProcessResult(outcome=RunOutcome.SIGNALED, signal=int(signal.SIGFPE))
    assert "division by zero" in explain_process_failure(divide, LIMITS)
    exited = ProcessResult(outcome=RunOutcome.EXITED, exit_code=3)
    assert "status 3" in explain_process_failure(exited, LIMITS)
