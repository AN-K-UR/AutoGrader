"""Weighted scoring, checked against hand-calculated values."""
import pytest

from agent.config_loader import DEFAULTS
from models.results import AnalyzerResult, MetricResult, MetricStatus
from scoring.score_calculator import calculate_score

POLICY = dict(DEFAULTS["scoring"])


def scored(name, weight, score):
    return MetricResult(name, "a", weight, AnalyzerResult.scored(score, ""))


def status(name, weight, value):
    return MetricResult(name, "a", weight, AnalyzerResult(status=value))


def test_hand_calculated_weighted_score():
    metrics = [scored("a", 0.5, 1.0), scored("b", 0.3, 0.5), scored("c", 0.2, 0.0)]
    summary = calculate_score(metrics, POLICY, True)
    assert summary.grade == 65.0            # 50 + 15 + 0
    assert summary.status == "complete"
    assert [metric.contribution for metric in metrics] == [50.0, 15.0, 0.0]


def test_the_assignment_example_sums_to_79_not_89():
    weights = [0.2] + [0.1] * 8
    scores = [0.9, 0.9, 0.6, 0.3, 0.8, 1.0, 1.0, 0.5, 1.0]
    metrics = [scored(f"m{i}", w, s) for i, (w, s) in enumerate(zip(weights, scores))]
    assert calculate_score(metrics, POLICY, True).grade == 79.0


def test_contributions_sum_to_the_grade():
    metrics = [scored("a", 0.7, 0.33), scored("b", 0.2, 0.71), scored("c", 0.1, 0.19)]
    summary = calculate_score(metrics, POLICY, True)
    assert sum(metric.contribution for metric in metrics) == pytest.approx(summary.grade, abs=0.01)


def test_weights_need_not_sum_to_one():
    assert calculate_score([scored("a", 30, 1.0), scored("b", 70, 0.5)], POLICY, True).grade == 65.0


def test_disabled_analyzer_is_excluded():
    metrics = [scored("a", 0.5, 0.8), status("b", 0.5, MetricStatus.DISABLED)]
    summary = calculate_score(metrics, POLICY, True)
    assert summary.grade == 80.0
    assert summary.excluded_metrics == ["b"]
    assert summary.status == "complete"
    assert summary.total_weight == 0.5


def test_unavailable_renormalizes_and_marks_partial():
    metrics = [scored("a", 0.5, 0.8), status("b", 0.5, MetricStatus.NOT_EVALUATED)]
    summary = calculate_score(metrics, POLICY, True)
    assert summary.grade == 80.0
    assert summary.status == "partial"
    assert summary.applicable_weight == 0.5


def test_unavailable_zero_policy():
    policy = dict(POLICY, unavailable_policy="zero")
    metrics = [scored("a", 0.5, 0.8), status("b", 0.5, MetricStatus.NOT_EVALUATED)]
    summary = calculate_score(metrics, policy, True)
    assert summary.grade == 40.0
    assert summary.zeroed_metrics == ["b"]


def test_blocked_scores_zero_and_stays_in_the_denominator():
    metrics = [scored("a", 0.5, 1.0), status("b", 0.5, MetricStatus.BLOCKED)]
    summary = calculate_score(metrics, POLICY, True)
    assert summary.grade == 50.0
    assert summary.status == "partial"


def test_a_skipped_check_never_earns_marks():
    for value in (MetricStatus.BLOCKED, MetricStatus.NOT_EVALUATED, MetricStatus.DISABLED):
        metrics = [scored("a", 0.5, 0.2), status("b", 0.5, value)]
        calculate_score(metrics, POLICY, True)
        assert metrics[1].contribution == 0.0


def test_compilation_failure_partial_policy_keeps_source_metrics():
    metrics = [scored("source", 0.4, 1.0), status("exec", 0.6, MetricStatus.BLOCKED)]
    assert calculate_score(metrics, POLICY, False).grade == 40.0


def test_compilation_failure_zero_policy():
    policy = dict(POLICY, compile_failure_policy="zero")
    metrics = [scored("source", 0.4, 1.0), status("exec", 0.6, MetricStatus.BLOCKED)]
    assert calculate_score(metrics, policy, False).grade == 0.0


def test_no_applicable_components_is_not_a_zero():
    summary = calculate_score([status("a", 1.0, MetricStatus.NOT_EVALUATED)], POLICY, True)
    assert summary.grade is None
    assert summary.status == "not_gradable"


def test_empty_metrics_avoids_division_by_zero():
    assert calculate_score([], POLICY, True).grade is None


def test_zero_weight_component_has_no_effect():
    metrics = [scored("a", 1.0, 0.5), scored("b", 0.0, 1.0)]
    summary = calculate_score(metrics, POLICY, True)
    assert summary.grade == 50.0
    assert "b" in summary.excluded_metrics


@pytest.mark.parametrize("score,grade", [(0.0, 0.0), (1.0, 100.0)])
def test_boundary_scores(score, grade):
    assert calculate_score([scored("a", 1.0, score)], POLICY, True).grade == grade


@pytest.mark.parametrize("score", [-0.01, 1.01])
def test_out_of_range_scores_are_rejected(score):
    with pytest.raises(ValueError):
        AnalyzerResult.scored(score, "")


def test_formula_and_policy_are_recorded():
    summary = calculate_score([scored("a", 1.0, 1.0)], POLICY, True)
    assert "sum(weight_i * score_i)" in summary.formula
    assert summary.policy["unavailable_policy"] == "renormalize"
