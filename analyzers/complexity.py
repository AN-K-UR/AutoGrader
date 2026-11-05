"""``complexity_estimator``: empirical growth estimate from operation counts.

The assignment's example uses a timing curve. Timing varies with machine load,
which would break "same submission + same rules -> same grade". Instead the
submission is built with basic-block counters (``runtime/op_counter.c``) and run
at each configured size. The counts are exact and repeatable, so the estimate is
too. It is still an estimate from samples, not a proof of asymptotic complexity.
"""
from __future__ import annotations

import math
import os
import random
import re
import shutil
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from analyzers.base import AnalysisContext, Analyzer, register
from analyzers.explain import explain_process_failure, run_binary
from execution.compiler import compile_source
from execution.process_runner import Limits
from models.results import AnalyzerResult, RunOutcome

_RUNTIME = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "execution", "runtime", "op_counter.c")
_OPS_LINE = re.compile(r"@@AG_OPS:(\d+)@@")
_FIELD = re.compile(r"\{ints:n:(-?\d+):(-?\d+)\}")
_MAX_SIZE_FOR_EXPONENTIAL = 60
_TOLERANCE = 0.05       # A fit this close is treated as fitting.
_CONSTANT_SPREAD = 0.05  # max/min within 5% counts as constant.

# Ordered from slowest-growing to fastest-growing.
GROWTH_CLASSES: List[Tuple[str, Callable[[float], float]]] = [
    ("O(1)", lambda n: 1.0),
    ("O(log n)", lambda n: math.log2(n) if n > 1 else 0.0),
    ("O(n)", lambda n: n),
    ("O(n log n)", lambda n: n * math.log2(n) if n > 1 else 0.0),
    ("O(n^2)", lambda n: n ** 2),
    ("O(n^3)", lambda n: n ** 3),
    ("O(2^n)", lambda n: 2.0 ** min(n, _MAX_SIZE_FOR_EXPONENTIAL)),
]
_RANK = {name.lower().replace(" ", ""): rank for rank, (name, _) in enumerate(GROWTH_CLASSES)}


def class_rank(bound: str) -> Optional[int]:
    return _RANK.get(bound.lower().replace(" ", "").replace("**", "^"))


def fit_error(sizes: Sequence[float], counts: Sequence[float],
              shape: Callable[[float], float]) -> float:
    """Relative RMS error of the best ``a + b * shape(n)`` fit with ``b >= 0``."""
    weights = [1.0 / max(count, 1.0) ** 2 for count in counts]
    xs = [shape(size) for size in sizes]
    total = sum(weights)
    mean_x = sum(w * x for w, x in zip(weights, xs)) / total
    mean_y = sum(w * y for w, y in zip(weights, counts)) / total
    denominator = sum(w * (x - mean_x) ** 2 for w, x in zip(weights, xs))
    slope = 0.0
    if denominator > 0:
        numerator = sum(w * (x - mean_x) * (y - mean_y)
                        for w, x, y in zip(weights, xs, counts))
        slope = max(numerator / denominator, 0.0)
    intercept = mean_y - slope * mean_x
    residuals = [(intercept + slope * x - y) / max(y, 1.0) for x, y in zip(xs, counts)]
    return math.sqrt(sum(value ** 2 for value in residuals) / len(residuals))


def estimate_growth(sizes: Sequence[int], counts: Sequence[int]) -> Tuple[str, Dict[str, float]]:
    """Pick the slowest-growing class that explains the counts.

    Preferring the slowest class within tolerance stops a two-parameter fit from
    choosing a faster class that only matches noise.
    """
    errors = {name: round(fit_error(sizes, counts, shape), 6)
              for name, shape in GROWTH_CLASSES}
    if max(counts) <= min(counts) * (1 + _CONSTANT_SPREAD):
        return "O(1)", errors
    best = min(errors.values())
    allowed = max(_TOLERANCE, best * 1.5)
    for name, _ in GROWTH_CLASSES[1:]:
        if errors[name] <= allowed:
            return name, errors
    return min(errors, key=errors.get), errors


def render_input(template: str, size: int, generator: random.Random) -> str:
    """Expand ``{n}`` and ``{ints:n:LOW:HIGH}`` in an input template."""
    def numbers(match: "re.Match[str]") -> str:
        low, high = int(match.group(1)), int(match.group(2))
        return " ".join(str(generator.randint(low, high)) for _ in range(size))

    return _FIELD.sub(numbers, template).replace("{n}", str(size))


def parse_ops(stderr: str) -> Optional[int]:
    """Take the last marker: the exit hook runs last, after any student output."""
    found = _OPS_LINE.findall(stderr)
    return int(found[-1]) if found else None


@register
class ComplexityAnalyzer(Analyzer):
    name = "complexity_estimator"
    needs_execution = True
    PARAMS = {
        "required": (str, True),
        "sizes": (list, True),
        "input_template": (str, False),
        "seed": (int, False),
        "time_limit_s": ((int, float), False),
        "penalty_per_class": ((int, float), False),
    }

    @classmethod
    def check_params(cls, params: Dict[str, Any]) -> List[str]:
        problems = []
        if isinstance(params.get("required"), str) and class_rank(params["required"]) is None:
            known = ", ".join(name for name, _ in GROWTH_CLASSES)
            problems.append(f"required must be one of {known}, got {params['required']!r}")
        sizes = params.get("sizes")
        if isinstance(sizes, list):
            if len(sizes) < 3:
                problems.append("sizes needs at least 3 entries to estimate growth")
            if any(isinstance(size, bool) or not isinstance(size, int) or size < 1
                   for size in sizes) or sizes != sorted(set(sizes)):
                problems.append("sizes must be strictly increasing positive integers")
        return problems

    def run(self, context: AnalysisContext, params: Dict[str, Any]) -> AnalyzerResult:
        binary, problem = self._build(context)
        if binary is None:
            return AnalyzerResult.not_evaluated(problem)

        rules = context.rules
        limits = Limits(time_s=float(params.get("time_limit_s", rules.time_limit_s)),
                        memory_mb=rules.memory_limit_mb,
                        output_bytes=rules.execution["max_output_bytes"],
                        max_processes=rules.execution["max_processes"])
        template = params.get("input_template", "{n}\n")
        generator = random.Random(params.get("seed", 42))
        sizes, counts = [], []
        for size in params["sizes"]:
            process = run_binary(context.backend, context.workdir, binary, limits,
                                 render_input(template, size, generator))
            if process.outcome == RunOutcome.EXITED:
                ops = parse_ops(process.stderr)
                if ops is None:
                    return AnalyzerResult.not_evaluated(
                        f"no operation count was reported at n={size}")
                sizes.append(size)
                counts.append(ops)
                continue
            why = explain_process_failure(process, limits)
            if process.outcome in (RunOutcome.TIMEOUT, RunOutcome.MEMORY_LIMIT):
                return AnalyzerResult.scored(
                    0.0, f"Exceeded a limit at n={size}, far from the required "
                         f"{params['required']}. {why}",
                    evidence={"required": params["required"], "failed_at_size": size,
                              "sizes": sizes, "operation_counts": counts},
                    suggestions=[f"Reduce the running time. It failed at n={size}: {why}"])
            # The submission caused this, so it must not fall out of the denominator.
            return AnalyzerResult.blocked(f"the program failed at n={size}: {why}")

        if len(sizes) < 3:
            return AnalyzerResult.not_evaluated("too few sizes completed to estimate growth")
        return self._verdict(params, sizes, counts)

    @staticmethod
    def _build(context: AnalysisContext) -> Tuple[Optional[str], str]:
        shutil.copyfile(_RUNTIME, os.path.join(context.workdir, "op_counter.c"))
        execution = context.rules.execution
        compiler, timeout = execution["compiler"], execution["compile_timeout_s"]
        runtime = compile_source(context.backend, compiler, ["op_counter.c"], "op_counter.o",
                                 ["-c", "-O1"], context.workdir, timeout)
        if not runtime.success:
            return None, "the operation counter did not compile"
        # -O0 stops the optimiser replacing a loop with a closed form, which would
        # make a linear algorithm look constant.
        built = compile_source(context.backend, compiler,
                               [context.source_file, "op_counter.o"], "counted.bin",
                               ["-O0", "-std=c11", "-w", "-fsanitize-coverage=trace-pc"],
                               context.workdir, timeout, execution["link_flags"])
        if not built.success:
            return None, ("this compiler does not support -fsanitize-coverage=trace-pc: "
                          + built.output[:200])
        return built.binary, ""

    @staticmethod
    def _verdict(params: Dict[str, Any], sizes: List[int], counts: List[int]) -> AnalyzerResult:
        required = params["required"]
        estimated, errors = estimate_growth(sizes, counts)
        excess = (class_rank(estimated) or 0) - (class_rank(required) or 0)
        penalty = float(params.get("penalty_per_class", 0.5))
        score = 1.0 if excess <= 0 else max(0.0, 1.0 - penalty * excess)
        evidence = {
            "required": required,
            "estimated": estimated,
            "sizes": sizes,
            "operation_counts": counts,
            "fit_errors": errors,
            "method": "basic-block counts at -O0, fitted to growth classes",
            "confidence": "low" if len(sizes) < 4 else "moderate",
        }
        if excess <= 0:
            return AnalyzerResult.scored(score, f"Estimated {estimated}, within the "
                                         f"required {required}.", evidence=evidence)
        return AnalyzerResult.scored(
            score, f"Estimated {estimated}, slower than the required {required}.",
            evidence=evidence,
            suggestions=[f"Your program grows like {estimated} but {required} is required. "
                         "Look for a nested loop that a better algorithm could remove."])
