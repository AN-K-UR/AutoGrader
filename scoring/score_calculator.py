"""Combines metric scores into one grade. Knows nothing about analyzers or reports.

    grade = 100 * sum(weight_i * score_i) / sum(applicable weights)

How each status enters that formula:

    scored          score as given
    blocked         score 0: the submission caused the skip
    not_evaluated   ``unavailable_policy``: "renormalize" removes the weight from
                    the denominator, "zero" keeps it and scores 0
    disabled        never counted

No path gives a skipped check a positive score.
"""
from __future__ import annotations

from typing import Any, Dict, List

from models.results import MetricResult, MetricStatus, ScoreSummary

FORMULA = "grade = 100 * sum(weight_i * score_i) / sum(applicable_weights)"
_GRADE_DECIMALS = 2


def calculate_score(metrics: List[MetricResult], policy: Dict[str, Any],
                    compiled: bool) -> ScoreSummary:
    """Fill each metric's contribution and return the overall summary."""
    unavailable = policy["unavailable_policy"]
    applicable: List[MetricResult] = []
    excluded: List[str] = []
    zeroed: List[str] = []

    for metric in metrics:
        status = metric.result.status
        if status == MetricStatus.DISABLED or metric.weight == 0:
            excluded.append(metric.name)
        elif status == MetricStatus.NOT_EVALUATED and unavailable == "renormalize":
            excluded.append(metric.name)
        else:
            applicable.append(metric)
            if status != MetricStatus.SCORED:
                zeroed.append(metric.name)

    total_weight = sum(metric.weight for metric in metrics
                       if metric.result.status != MetricStatus.DISABLED)
    denominator = sum(metric.weight for metric in applicable)
    summary = ScoreSummary(
        grade=None, status="not_gradable", formula=FORMULA,
        applicable_weight=round(denominator, 6), total_weight=round(total_weight, 6),
        excluded_metrics=excluded, zeroed_metrics=zeroed,
        policy={key: str(value) for key, value in policy.items()},
    )
    if denominator <= 0:
        return summary

    zero_everything = not compiled and policy["compile_failure_policy"] == "zero"
    grade = 0.0
    for metric in applicable:
        score = metric.result.score
        if zero_everything or score is None:
            score = 0.0
        metric.max_contribution = round(100.0 * metric.weight / denominator, 4)
        metric.contribution = round(100.0 * metric.weight * score / denominator, 4)
        grade += metric.weight * score
    summary.grade = round(100.0 * grade / denominator, _GRADE_DECIMALS)
    incomplete = bool(zeroed or any(metric.result.status == MetricStatus.NOT_EVALUATED
                                    for metric in metrics))
    summary.status = "partial" if incomplete else "complete"
    return summary
