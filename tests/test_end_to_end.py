"""Whole-agent runs on the sample submissions."""
import json
import os
import shutil

import pytest

from agent.config_loader import load_rules
from agent.coordinator import SubmissionError, dispatch, evaluate
from agent.result_manager import Workspace
from analyzers.base import get_analyzer
from models.results import MetricStatus
from reporting.json_report import build_report

EXAMPLES = "submissions/examples"
EXECUTION_METRICS = {"correctness", "logical", "complexity", "memory_safety"}
SOURCE_METRICS = {"syntax", "structure", "modularity", "readability", "originality"}


def grade(name, rules="config/rules.json"):
    return evaluate(f"{EXAMPLES}/{name}", load_rules(rules), allow_llm=False)


def metric(evaluation, name):
    return next(item for item in evaluation.metrics if item.name == name)


def test_correct_program_scores_well():
    evaluation = grade("add_correct.c")
    assert evaluation.summary.grade >= 99
    assert evaluation.summary.status == "complete"
    assert metric(evaluation, "correctness").result.evidence["tests_passed"] == 10
    assert evaluation.feedback["where_you_failed"] == []


def test_assignment_example_exposes_the_overflow():
    evaluation = grade("add_student.c")
    inputs = [item["input"] for item in evaluation.feedback["where_you_failed"]]
    assert "2147483647 1\n" in inputs
    assert metric(evaluation, "modularity").result.evidence["functions_defined"] == 1
    assert metric(evaluation, "complexity").result.evidence["estimated"] == "O(1)"


def test_incorrect_program_fails_tests_but_is_graded():
    evaluation = grade("add_wrong.c")
    assert metric(evaluation, "correctness").result.score < 0.5
    assert evaluation.feedback["where_you_failed"]


def test_compilation_failure_is_a_partial_report_not_a_crash():
    evaluation = grade("add_compile_error.c")
    assert not evaluation.first_pass.compiled
    assert evaluation.summary.status == "partial"
    for name in EXECUTION_METRICS:
        assert metric(evaluation, name).result.status == MetricStatus.BLOCKED
    assert metric(evaluation, "syntax").result.score == 0.0
    assert metric(evaluation, "readability").result.status == MetricStatus.SCORED
    assert any(item["metric"] == "compilation" and "stdoi.h" in item["text"]
               for item in evaluation.feedback["suggestions"])


def test_never_halting_program_follows_the_assignment_flow():
    evaluation = grade("add_infinite_loop.c")
    assert evaluation.first_pass.suspected_infinite_loop
    assert {"type": "suspected_infinite_loop"} in evaluation.flags
    for name in EXECUTION_METRICS:
        assert metric(evaluation, name).result.status == MetricStatus.BLOCKED
    for name in SOURCE_METRICS:
        assert metric(evaluation, name).result.status == MetricStatus.SCORED
    assert evaluation.summary.grade <= 50


def test_crash_is_survived():
    evaluation = grade("add_crash.c")
    assert evaluation.first_pass.smoke_crashed
    assert metric(evaluation, "correctness").result.score == 0.0
    assert metric(evaluation, "complexity").result.status == MetricStatus.BLOCKED


def test_nonzero_exit_loses_correctness():
    assert metric(grade("add_exit_error.c"), "correctness").result.score == 0.0


def test_memory_bug_found_though_all_tests_pass():
    evaluation = grade("add_memory_bug.c")
    assert metric(evaluation, "correctness").result.score == 1.0
    messages = [item["message"] for item in
                metric(evaluation, "memory_safety").result.evidence["diagnostics"]]
    assert "heap-buffer-overflow" in messages


def test_leak_is_highlighted():
    assert "not_freed_at_exit" in metric(grade("add_leak.c"), "memory_safety").result.evidence


def test_static_issue_found_by_cppcheck():
    from analyzers.static_analysis import find_tool
    if find_tool("cppcheck") is None:
        pytest.skip("cppcheck not installed")
    findings = metric(grade("add_static_issue.c"), "structure").result.evidence["cppcheck_findings"]
    assert any(item["code"] == "arrayIndexOutOfBounds" for item in findings)


def test_complex_function_gets_feedback():
    result = metric(grade("add_complex.c"), "structure").result
    assert any("cyclomatic complexity" in text for text in result.suggestions)


def test_renamed_copy_is_flagged_for_review():
    evaluation = grade("add_copied.c")
    flags = [flag for flag in evaluation.flags if flag["type"] == "suspected_copying"]
    assert flags and flags[0]["source_kind"] == "peers"
    assert "peer_a.c" in flags[0]["target"]


def test_independent_program_is_not_flagged():
    assert not [flag for flag in grade("add_correct.c").flags
                if flag["type"] == "suspected_copying"]


def test_inefficient_sort_is_separated_from_efficient_sort():
    rules = "config/rules_sort.json"
    good = metric(grade("sort_correct.c", rules), "complexity").result
    slow = metric(grade("sort_bubble.c", rules), "complexity").result
    assert good.evidence["estimated"] == "O(n log n)" and good.score == 1.0
    assert slow.evidence["estimated"] == "O(n^2)" and slow.score < 1.0


def test_subtraction_comparator_bug_is_found():
    evaluation = grade("sort_overflow_compare.c", "config/rules_sort.json")
    categories = {item.category for item in metric(evaluation, "logical").result.counterexamples}
    assert "extreme_values" in categories


@pytest.mark.parametrize("name", ["add_student.c", "add_wrong.c", "add_infinite_loop.c",
                                  "add_compile_error.c"])
def test_same_submission_same_rules_same_grade(name):
    rules = load_rules("config/rules.json")
    first = evaluate(f"{EXAMPLES}/{name}", rules, allow_llm=False)
    second = evaluate(f"{EXAMPLES}/{name}", rules, allow_llm=False)
    assert first.summary.grade == second.summary.grade
    assert first.fingerprint() == second.fingerprint()


def test_grade_does_not_depend_on_the_working_directory(tmp_path, monkeypatch):
    source = os.path.abspath(f"{EXAMPLES}/add_student.c")
    rules_path = os.path.abspath("config/rules.json")
    first = evaluate(source, load_rules(rules_path), allow_llm=False).summary.grade
    monkeypatch.chdir(tmp_path)
    assert evaluate(source, load_rules(rules_path), allow_llm=False).summary.grade == first


def test_changing_only_the_rules_changes_the_grade(tmp_path):
    document = json.load(open("config/rules.json", encoding="utf-8"))
    for item in document["metrics"]:
        item["weight"] = 1.0 if item["name"] == "correctness" else 0.0
    for section, target in (("test_cases", "test_cases"), ("references", "references"),
                            ("corpus", "corpus")):
        shutil.copytree(section, tmp_path / target)
    (tmp_path / "config").mkdir()
    path = tmp_path / "config" / "rules.json"
    path.write_text(json.dumps(document))
    evaluation = evaluate(f"{EXAMPLES}/add_student.c", load_rules(str(path)), allow_llm=False)
    assert evaluation.summary.grade == 80.0


def test_analyzer_failure_is_contained(monkeypatch):
    def explode(self, context, params):
        raise RuntimeError("boom")
    monkeypatch.setattr(get_analyzer("function_split"), "run", explode)
    evaluation = grade("add_correct.c")
    result = metric(evaluation, "modularity").result
    assert result.status == MetricStatus.NOT_EVALUATED
    assert "boom" in result.reason
    assert evaluation.summary.grade is not None


def test_results_keep_rule_order():
    names = [item.name for item in grade("add_correct.c").metrics]
    assert names == [item.name for item in load_rules("config/rules.json").metrics]


def test_source_only_analyzers_are_not_marked_as_execution():
    for name in ("compiler_warnings", "static_analysis", "function_split", "llm_review",
                 "similarity_flag", "pattern_check"):
        assert not get_analyzer(name).needs_execution
    for name in ("io_tests", "edge_case_runner", "complexity_estimator", "sanitizer_run"):
        assert get_analyzer(name).needs_execution


def test_disabled_metric_is_reported_and_excluded(tmp_path):
    document = json.load(open("config/rules.json", encoding="utf-8"))
    document["metrics"] = [item for item in document["metrics"]
                           if item["name"] in ("modularity", "readability")]
    document["metrics"][0]["weight"] = 1.0
    document["metrics"][1]["enabled"] = False
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(document))
    evaluation = evaluate(f"{EXAMPLES}/add_correct.c", load_rules(str(path)), allow_llm=False)
    assert metric(evaluation, "readability").result.status == MetricStatus.DISABLED
    assert "readability" in evaluation.summary.excluded_metrics
    assert build_report(evaluation)["grade"] == evaluation.summary.grade


@pytest.mark.parametrize("path,message", [
    ("/nonexistent/file.c", "not found"), ("README.md", "expected a .c file")])
def test_bad_submission_paths(path, message):
    with pytest.raises(SubmissionError, match=message):
        evaluate(path, load_rules("config/rules.json"))


def test_hostile_file_name_is_only_ever_text(tmp_path, monkeypatch):
    hostile = tmp_path / "$(touch ran); x.c"
    shutil.copyfile(f"{EXAMPLES}/add_correct.c", hostile)
    rules = load_rules(os.path.abspath("config/rules.json"))
    monkeypatch.chdir(tmp_path)
    evaluation = evaluate(str(hostile), rules, allow_llm=False)
    assert evaluation.first_pass.compiled
    assert not (tmp_path / "ran").exists()


def test_temporary_directory_is_removed():
    with Workspace() as workspace:
        path = workspace.path
        assert os.path.isdir(path)
    assert not os.path.exists(path)


def test_temporary_directory_is_removed_after_an_error():
    with pytest.raises(RuntimeError):
        with Workspace() as workspace:
            path = workspace.path
            raise RuntimeError
    assert not os.path.exists(path)


def test_evaluation_leaves_no_workspace_behind(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", None)
    grade("add_correct.c")
    assert not list(tmp_path.glob("autograder-*"))
