"""Structured result objects shared by every layer of the agent.

Everything here is plain data. Analyzers produce it, scoring reads it, and
reporting serialises it, so those layers never need to import each other.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class MetricStatus(str, Enum):
    """Why a metric does or does not have a score.

    The split between BLOCKED and NOT_EVALUATED is the key scoring distinction:
    BLOCKED is caused by the submission and scores zero, NOT_EVALUATED is caused
    by the environment and is handled by ``scoring.unavailable_policy``.
    """

    SCORED = "scored"
    BLOCKED = "blocked"
    NOT_EVALUATED = "not_evaluated"
    DISABLED = "disabled"


class RunOutcome(str, Enum):
    """How a child process ended."""

    EXITED = "exited"
    SIGNALED = "signaled"
    TIMEOUT = "timeout"
    MEMORY_LIMIT = "memory_limit"
    OUTPUT_LIMIT = "output_limit"
    FAILED_TO_START = "failed_to_start"


@dataclass
class ProcessResult:
    """Outcome of one child process, whichever backend ran it."""

    outcome: RunOutcome
    exit_code: Optional[int] = None
    signal: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    duration_s: float = 0.0
    peak_memory_kb: Optional[int] = None
    error: str = ""

    @property
    def clean_exit(self) -> bool:
        return self.outcome == RunOutcome.EXITED and self.exit_code == 0


@dataclass
class Diagnostic:
    """One finding from a compiler, analyzer, or sanitizer."""

    tool: str
    severity: str
    message: str
    line: Optional[int] = None
    column: Optional[int] = None
    code: Optional[str] = None


@dataclass
class CompileResult:
    success: bool
    compiler: str
    flags: List[str]
    exit_code: Optional[int] = None
    output: str = ""
    diagnostics: List[Diagnostic] = field(default_factory=list)
    binary: Optional[str] = None
    error: str = ""
    timed_out: bool = False


@dataclass
class Counterexample:
    """A concrete input that exposes a failure (assignment requirement 5)."""

    test_id: str
    input: str
    expected: Optional[str]
    got: str
    why: str
    origin: str  # "testset" or "generated"
    category: Optional[str] = None
    outcome: str = "wrong_output"


@dataclass
class TestCaseResult:
    test_id: str
    status: str  # passed, failed, timeout, crashed, memory_limit, output_limit, invalid
    description: str = ""
    input: str = ""
    expected: Optional[str] = None
    actual: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    duration_s: Optional[float] = None
    peak_memory_kb: Optional[int] = None
    comparison: str = ""
    diagnostic: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "passed"


@dataclass
class AnalyzerResult:
    """What every analyzer returns: a score, its evidence, and feedback."""

    status: MetricStatus
    score: Optional[float] = None
    feedback: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    suggestions: List[str] = field(default_factory=list)
    counterexamples: List[Counterexample] = field(default_factory=list)
    flags: List[Dict[str, Any]] = field(default_factory=list)
    skipped_tools: List[Dict[str, str]] = field(default_factory=list)
    reason: str = ""

    @classmethod
    def scored(cls, score: float, feedback: str, **extra: Any) -> "AnalyzerResult":
        if not 0.0 <= score <= 1.0:
            raise ValueError(f"score must be within [0, 1], got {score}")
        return cls(status=MetricStatus.SCORED, score=round(score, 4),
                   feedback=feedback, **extra)

    @classmethod
    def not_evaluated(cls, reason: str, **extra: Any) -> "AnalyzerResult":
        return cls(status=MetricStatus.NOT_EVALUATED, feedback=reason,
                   reason=reason, **extra)

    @classmethod
    def blocked(cls, reason: str) -> "AnalyzerResult":
        return cls(status=MetricStatus.BLOCKED, feedback=reason, reason=reason)


@dataclass
class MetricResult:
    """An analyzer's result, placed within the rule that requested it."""

    name: str
    analyzer: str
    weight: float
    result: AnalyzerResult
    threshold: Optional[float] = None
    met_threshold: Optional[bool] = None
    contribution: float = 0.0
    max_contribution: float = 0.0


@dataclass
class FirstPass:
    compiled: bool = False
    smoke_ok: bool = False
    smoke_ran: bool = False
    suspected_infinite_loop: bool = False
    smoke_crashed: bool = False
    smoke_detail: str = ""
    static_sanity: Dict[str, bool] = field(default_factory=dict)


@dataclass
class ScoreSummary:
    grade: Optional[float]
    status: str  # complete, partial, not_gradable
    formula: str
    applicable_weight: float
    total_weight: float
    excluded_metrics: List[str] = field(default_factory=list)
    zeroed_metrics: List[str] = field(default_factory=list)
    policy: Dict[str, str] = field(default_factory=dict)


def to_plain(value: Any) -> Any:
    """Convert dataclasses and enums into JSON-compatible values."""
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(v) for v in value]
    return value
