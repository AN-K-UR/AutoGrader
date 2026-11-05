import json
import re

import pytest

from agent.config_loader import load_rules
from agent.coordinator import evaluate
from reporting.json_report import SCHEMA_VERSION, build_report, clip_text, clip_tree, write_json
from reporting.text_report import render_text, write_text


@pytest.fixture(scope="module")
def graded():
    return build_report(evaluate("submissions/examples/add_student.c",
                                 load_rules("config/rules.json"), allow_llm=False))


REQUIRED_KEYS = """schema_version submission submission_id source_hash rules_hash testset_hash
timestamp grade evaluation_status grade_fingerprint scoring first_pass compilation execution
metrics flags feedback tool_versions usefulness_limitations""".split()


def test_json_round_trip_has_the_required_fields(graded, tmp_path):
    path = tmp_path / "r.json"
    write_json(graded, str(path))
    loaded = json.loads(path.read_text())
    for key in REQUIRED_KEYS:
        assert key in loaded
    assert loaded["schema_version"] == SCHEMA_VERSION


def test_grades_agree_between_reports(graded, tmp_path):
    path = tmp_path / "r.txt"
    write_text(graded, str(path))
    match = re.search(r"Overall grade: ([\d.]+) / 100", path.read_text())
    assert float(match.group(1)) == graded["grade"]


def test_text_report_has_all_sections(graded):
    text = render_text(graded)
    for heading in ("Overall grade", "Metric", "--- Compilation ---", "--- Test cases ---",
                    "--- Where you failed ---", "--- Code analysis findings ---",
                    "--- Readability and complexity ---", "--- Similarity ---",
                    "--- Skipped checks and limitations ---",
                    "--- Suggestions to raise the grade ---",
                    "Usefulness and limitations"):
        assert heading in text


def test_failures_show_input_expected_and_why(graded):
    text = render_text(graded)
    assert "INPUT:    2147483647 1" in text
    assert "EXPECTED: 2147483648" in text
    assert "GOT:      -2147483648" in text
    assert "WHY:" in text


def test_assignment_needs_three_to_four_examples_with_concrete_limits(graded):
    block = graded["usefulness_limitations"]
    assert 3 <= len(block["usefulness"]) <= 5
    assert 3 <= len(block["limitations"]) <= 5
    assert all(item["example"] for item in block["limitations"])


def test_reports_do_not_leak_host_paths(graded):
    assert "/Users/" not in json.dumps(graded)


def test_metric_contributions_sum_to_the_grade(graded):
    total = sum(metric["contribution"] for metric in graded["metrics"])
    assert total == pytest.approx(graded["grade"], abs=0.01)


def test_clip_text_is_bounded_and_says_so():
    clipped = clip_text("x" * 5000, 100)
    assert clipped.startswith("x" * 100)
    assert "4900 bytes removed" in clipped
    assert clip_text("short", 100) == "short"


def test_clip_handles_multibyte_boundaries():
    assert "bytes removed" in clip_text("é" * 100, 51)


def test_large_diagnostic_output_is_limited_everywhere():
    tree = {"a": ["y" * 9000], "b": {"c": "z" * 9000}, "d": 5}
    clipped = clip_tree(tree, 100)
    assert len(clipped["a"][0]) < 200 and len(clipped["b"]["c"]) < 200
    assert clipped["d"] == 5


def test_report_without_optional_sections_still_renders(graded):
    trimmed = dict(graded)
    trimmed.pop("usefulness_limitations")
    trimmed["metrics"] = [metric for metric in graded["metrics"]
                          if metric["analyzer"] == "function_split"]
    text = render_text(trimmed)
    assert "Test cases were not run." in text
    assert "Not part of these rules." in text


def test_not_gradable_report_says_so_instead_of_zero(graded):
    changed = dict(graded, grade=None, evaluation_status="not_gradable")
    assert "NOT GRADABLE" in render_text(changed)
