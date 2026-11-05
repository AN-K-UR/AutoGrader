"""Analyzers that run the program, against real compiled fixtures."""
import pytest

from analyzers.base import get_analyzer
from analyzers.complexity import parse_ops
from analyzers.edge_cases import generate_cases
from analyzers.memory_safety import defect_label, parse_leak_marker, parse_sanitizer_output
from analyzers.testset import compare_output, load_testset
from conftest import ADD
from models.results import MetricStatus

LOOPS_FOREVER = "int main(void) { volatile int on = 1; while (on) { } return 0; }\n"
CRASHES = "int main(void) { volatile int *p = 0; *p = 1; return 0; }\n"
SILENT = "int main(void) { return 0; }\n"
FAILS = '#include <stdio.h>\nint main(void) { puts("12"); return 2; }\n'
FLOODS = '#include <stdio.h>\nint main(void) { for (;;) { puts("xxxxxxxxxxxxxxxx"); } }\n'
WRAPS = """#include <stdio.h>
int main(void) { int a, b; scanf("%d %d", &a, &b); printf("%d\\n", a + b); return 0; }
"""
LINEAR = """#include <stdio.h>
int main(void) { long total = 0; int n; scanf("%d", &n);
for (int i = 0; i < n; i++) { total += i; } printf("%ld\\n", total); return 0; }
"""
QUADRATIC = """#include <stdio.h>
int main(void) { long total = 0; int n; scanf("%d", &n);
for (int i = 0; i < n; i++) { for (int j = 0; j < n; j++) { total += j; } }
printf("%ld\\n", total); return 0; }
"""
OVERRUN = """#include <stdlib.h>
#include <stdio.h>
int main(void) { int *p = malloc(4 * sizeof(int)); p[4] = 1; printf("%d\\n", p[0]); free(p); return 0; }
"""
LEAK = """#include <stdlib.h>
#include <stdio.h>
int main(void) { int *p = malloc(100); *p = 1; printf("%d\\n", *p); return 0; }
"""
TIDY = """#include <stdlib.h>
#include <stdio.h>
int main(void) { int *p = malloc(100); *p = 1; printf("%d\\n", *p); free(p); return 0; }
"""
SIMPLE_CASES = [("01", "7 5\n", "12\n"), ("02", "1 1\n", "2\n")]


def io_tests(context_factory, write_tests, source, cases=SIMPLE_CASES, params=None):
    directory = write_tests(cases)
    merged = dict({"testset_dir": str(directory)}, **(params or {}))
    context = context_factory(source, [{"name": "c", "analyzer": "io_tests", "weight": 1.0,
                                        "params": merged}])
    return get_analyzer("io_tests")().run(context, merged)


# Correctness ---------------------------------------------------------------

def test_correct_output_passes(context_factory, write_tests):
    result = io_tests(context_factory, write_tests, ADD)
    assert result.score == 1.0
    assert result.evidence["tests_passed"] == 2
    assert not result.counterexamples


def test_incorrect_output_gives_a_counterexample(context_factory, write_tests):
    result = io_tests(context_factory, write_tests, ADD.replace("a + b", "a * b"))
    assert result.score == 0.0
    example = result.counterexamples[0]
    assert (example.input, example.expected, example.got) == ("7 5\n", "12\n", "35\n")
    assert example.why


def test_nonzero_exit_fails_even_with_right_output(context_factory, write_tests):
    result = io_tests(context_factory, write_tests, FAILS, [("01", "", "12\n")])
    assert result.score == 0.0
    assert "status 2" in result.counterexamples[0].why


def test_nonzero_exit_can_be_allowed(context_factory, write_tests):
    result = io_tests(context_factory, write_tests, FAILS, [("01", "", "12\n")],
                      {"require_zero_exit": False})
    assert result.score == 1.0


def test_empty_output_is_a_failure(context_factory, write_tests):
    result = io_tests(context_factory, write_tests, SILENT)
    assert result.score == 0.0
    assert "printed nothing" in result.counterexamples[0].why


def test_timeout_is_recorded(context_factory, write_tests):
    result = io_tests(context_factory, write_tests, LOOPS_FOREVER, [("01", "", "x\n")])
    assert result.evidence["results"][0]["status"] == "timeout"
    assert result.score == 0.0


def test_crash_is_recorded(context_factory, write_tests):
    result = io_tests(context_factory, write_tests, CRASHES, [("01", "", "x\n")])
    assert result.evidence["results"][0]["status"] == "crashed"
    assert "SIG" in result.evidence["results"][0]["diagnostic"]


def test_excessive_output_is_contained(context_factory, write_tests):
    result = io_tests(context_factory, write_tests, FLOODS, [("01", "", "x\n")])
    assert result.evidence["results"][0]["status"] == "output_limit"
    assert len(result.evidence["results"][0]["actual"]) <= 1_000_000


def test_independent_tests_continue_after_a_failure(context_factory, write_tests):
    cases = [("01", "1 1\n", "3\n"), ("02", "7 5\n", "12\n")]
    result = io_tests(context_factory, write_tests, ADD, cases)
    assert [item["status"] for item in result.evidence["results"]] == ["failed", "passed"]
    assert result.score == 0.5


def test_no_test_cases_is_not_evaluated(context_factory, write_tests):
    result = io_tests(context_factory, write_tests, ADD, [])
    assert result.status == MetricStatus.NOT_EVALUATED


def test_missing_test_directory_is_not_evaluated(context_factory, tmp_path):
    params = {"testset_dir": str(tmp_path / "absent")}
    context = context_factory(ADD, [{"name": "c", "analyzer": "io_tests", "weight": 1.0,
                                     "params": params}])
    assert get_analyzer("io_tests")().run(context, params).status == MetricStatus.NOT_EVALUATED


def test_malformed_test_is_not_counted_as_a_pass(context_factory, write_tests, tmp_path):
    directory = write_tests(SIMPLE_CASES)
    (directory / "03.in").write_text("orphan input\n")
    (directory / "04.out").write_text("orphan output\n")
    params = {"testset_dir": str(directory)}
    context = context_factory(ADD, [{"name": "c", "analyzer": "io_tests", "weight": 1.0,
                                     "params": params}])
    result = get_analyzer("io_tests")().run(context, params)
    assert result.evidence["tests_total"] == 2
    problems = {item["test_id"]: item["problem"] for item in result.evidence["malformed_tests"]}
    assert problems == {"03": "missing expected-output file", "04": "missing input file"}


def test_all_tests_malformed_is_not_evaluated(context_factory, tmp_path):
    directory = tmp_path / "bad"
    directory.mkdir()
    (directory / "01.in").write_text("x")
    params = {"testset_dir": str(directory)}
    context = context_factory(ADD, [{"name": "c", "analyzer": "io_tests", "weight": 1.0,
                                     "params": params}])
    result = get_analyzer("io_tests")().run(context, params)
    assert result.status == MetricStatus.NOT_EVALUATED


def test_per_test_time_limit_and_metadata(write_tests):
    directory = write_tests(SIMPLE_CASES)
    (directory / "01.meta.json").write_text(
        '{"description": "sample", "time_limit_s": 0.5, "comparison": "exact"}')
    case = load_testset(str(directory))[0]
    assert (case.description, case.time_limit_s, case.comparison) == ("sample", 0.5, "exact")


def test_invalid_metadata_marks_the_test_malformed(write_tests):
    directory = write_tests(SIMPLE_CASES)
    (directory / "01.meta.json").write_text('{"comparison": "fuzzy"}')
    assert "unknown comparison" in load_testset(str(directory))[0].error


# Output comparison ---------------------------------------------------------

def test_exact_comparison_is_strict():
    assert compare_output("1\n", "1\n", "exact")[0]
    assert not compare_output("1\n", "1", "exact")[0]


def test_trim_trailing_records_what_it_forgave():
    matches, note = compare_output("1\n", "1  \n\n", "trim_trailing")
    assert matches and "trailing whitespace" in note
    assert not compare_output("1 2\n", "1  2\n", "trim_trailing")[0]


def test_normalize_whitespace():
    matches, note = compare_output("1 2\n", "1\n2", "normalize_whitespace")
    assert matches and note
    assert not compare_output("1 2\n", "1 3\n", "normalize_whitespace")[0]


# Edge cases ----------------------------------------------------------------

def edge_context(context_factory, tmp_path, source, params=None):
    reference = tmp_path / "reference.c"
    reference.write_text(ADD)
    merged = dict({"cases": ["negatives", "zero", "int_overflow", "whitespace", "random"],
                   "input_spec": {"kind": "ints", "count": 2},
                   "reference_solution": "reference.c"}, **(params or {}))
    context = context_factory(source, [{"name": "e", "analyzer": "edge_case_runner",
                                        "weight": 1.0, "params": merged}])
    return get_analyzer("edge_case_runner")().run(context, merged)


def test_generated_cases_find_an_overflow(context_factory, tmp_path):
    result = edge_context(context_factory, tmp_path, WRAPS)
    assert "int_overflow" in result.feedback
    example = next(item for item in result.counterexamples if item.category == "int_overflow")
    assert example.expected.strip() != example.got.strip()
    assert "32-bit" in example.why
    assert example.origin == "generated"


def test_correct_program_passes_every_generated_case(context_factory, tmp_path):
    result = edge_context(context_factory, tmp_path, ADD)
    assert result.score == 1.0


def test_shortest_counterexample_comes_first(context_factory, tmp_path):
    result = edge_context(context_factory, tmp_path, WRAPS)
    lengths = [len(item.input) for item in result.counterexamples]
    assert lengths == sorted(lengths)


def test_no_reference_only_detects_crashes(context_factory, tmp_path):
    params = {"cases": ["zero"], "input_spec": {"kind": "ints"}}
    context = context_factory(CRASHES, [{"name": "e", "analyzer": "edge_case_runner",
                                         "weight": 1.0, "params": params}])
    result = get_analyzer("edge_case_runner")().run(context, params)
    assert result.score == 0.0
    assert result.counterexamples[0].expected is None
    assert result.evidence["oracle"].startswith("none")


def test_missing_reference_is_not_evaluated(context_factory):
    params = {"cases": ["zero"], "reference_solution": "absent.c"}
    context = context_factory(ADD, [{"name": "e", "analyzer": "edge_case_runner",
                                     "weight": 1.0, "params": params}])
    result = get_analyzer("edge_case_runner")().run(context, params)
    assert result.status == MetricStatus.NOT_EVALUATED


def test_generation_is_deterministic():
    spec = {"kind": "array"}
    first = generate_cases(spec, ["all"], 7, 5)
    assert [item.input for item in first] == [item.input for item in generate_cases(spec, ["all"], 7, 5)]
    assert [item.input for item in first] != [item.input for item in generate_cases(spec, ["all"], 8, 5)]


def test_all_expands_to_every_category():
    categories = {item.category for item in generate_cases({"kind": "array"}, ["all"], 1, 1)}
    assert {"empty_array", "single_element", "duplicates", "extreme_values"} <= categories


# Complexity ----------------------------------------------------------------

def complexity(context_factory, source, required="O(n)", sizes=(100, 200, 400, 800, 1600)):
    params = {"required": required, "sizes": list(sizes), "input_template": "{n}\n"}
    context = context_factory(source, [{"name": "t", "analyzer": "complexity_estimator",
                                        "weight": 1.0, "params": params}])
    return get_analyzer("complexity_estimator")().run(context, params)


def test_linear_program_is_measured_as_linear(context_factory):
    result = complexity(context_factory, LINEAR)
    assert result.evidence["estimated"] == "O(n)"
    assert result.score == 1.0


def test_quadratic_program_loses_marks(context_factory):
    result = complexity(context_factory, QUADRATIC)
    assert result.evidence["estimated"] == "O(n^2)"
    assert result.score == 0.0
    assert any("O(n^2)" in text for text in result.suggestions)


def test_one_class_over_gets_partial_credit(context_factory):
    assert complexity(context_factory, QUADRATIC, "O(n log n)").score == 0.5


def test_faster_than_required_gets_full_marks(context_factory):
    assert complexity(context_factory, LINEAR, "O(n^2)").score == 1.0


def test_operation_counts_are_identical_across_runs(context_factory):
    first = complexity(context_factory, LINEAR).evidence["operation_counts"]
    second = complexity(context_factory, LINEAR).evidence["operation_counts"]
    assert first == second


def test_timeout_during_measurement_scores_zero(context_factory):
    result = complexity(context_factory, LOOPS_FOREVER)
    assert result.score == 0.0
    assert result.evidence["failed_at_size"] == 100


def test_crash_during_measurement_is_blocked_not_excused(context_factory):
    assert complexity(context_factory, CRASHES).status == MetricStatus.BLOCKED


def test_ops_marker_takes_the_last_value():
    assert parse_ops("@@AG_OPS:1@@\nnoise\n@@AG_OPS:99@@\n") == 99
    assert parse_ops("nothing") is None


# Memory safety -------------------------------------------------------------

def sanitize(context_factory, source, params=None):
    merged = dict({"extra_inputs": ["1 2\n"]}, **(params or {}))
    context = context_factory(source, [{"name": "m", "analyzer": "sanitizer_run",
                                        "weight": 1.0, "params": merged}])
    return get_analyzer("sanitizer_run")().run(context, merged)


def test_heap_overflow_detected_with_line(context_factory):
    result = sanitize(context_factory, OVERRUN)
    assert result.score < 1
    item = result.evidence["diagnostics"][0]
    assert item["message"] == "heap-buffer-overflow" and item["line"] == 3


def test_signed_overflow_detected(context_factory):
    context_input = {"extra_inputs": ["2147483647 1\n"]}
    result = sanitize(context_factory, WRAPS, context_input)
    assert any("signed integer overflow" in item["message"]
               for item in result.evidence["diagnostics"])


def test_one_defect_hit_by_many_inputs_counts_once(context_factory):
    result = sanitize(context_factory, WRAPS,
                      {"extra_inputs": ["2147483647 1\n", "2147483647 2\n"]})
    assert len(result.evidence["diagnostics"]) == 1
    assert result.score == 0.75


def test_defect_label_ignores_addresses_and_values():
    first = defect_label("store to address 0x6020000000e0 with insufficient space")
    second = defect_label("store to address 0x60200000ffff with insufficient space")
    assert first == second
    assert defect_label("signed integer overflow: 1 + 2 cannot be represented") == \
        defect_label("signed integer overflow: 3 + 4 cannot be represented")
    assert first != defect_label("division by zero")


def test_clean_program_is_not_called_safe(context_factory):
    result = sanitize(context_factory, TIDY)
    assert result.score == 1.0
    assert "does not prove" in result.evidence["note"]
    assert "safe" not in result.feedback.lower()


def test_leak_is_reported_with_size(context_factory):
    result = sanitize(context_factory, LEAK)
    assert result.evidence["not_freed_at_exit"] == {"blocks": 1, "bytes": 100}
    assert result.score == 0.75


def test_leak_check_can_be_disabled(context_factory):
    assert sanitize(context_factory, LEAK, {"check_leaks": False}).score == 1.0


def test_no_inputs_is_not_evaluated(context_factory):
    assert sanitize(context_factory, TIDY, {"extra_inputs": []}).status == MetricStatus.NOT_EVALUATED


def test_unsupported_sanitizer_is_not_evaluated(context_factory):
    result = sanitize(context_factory, TIDY, {"flags": "-fsanitize=no-such-sanitizer"})
    assert result.status == MetricStatus.NOT_EVALUATED
    assert result.score is None


def test_parsers_handle_linux_style_reports():
    text = ("==1==ERROR: AddressSanitizer: stack-buffer-overflow on address\n"
            "    #0 0x1 in main /work/submission.c:12:3\n"
            "submission.c:9:5: runtime error: division by zero\n"
            "==1==ERROR: LeakSanitizer: detected memory leaks\n")
    found = parse_sanitizer_output(text)
    assert [item["kind"] for item in found] == ["memory_error", "undefined_behavior", "leak"]
    assert found[0]["line"] == 12
    assert found[1]["message"] == "division by zero"


def test_leak_marker_parse():
    assert parse_leak_marker("x\n@@AG_LEAK:2:64@@\n") == (2, 64)
    assert parse_leak_marker("") is None


# Syntax --------------------------------------------------------------------

def syntax(context_factory, source, flags="-Wall -Wextra -Werror -std=c11"):
    params = {"flags": flags}
    context = context_factory(source, [{"name": "s", "analyzer": "compiler_warnings",
                                        "weight": 1.0, "params": params}])
    return get_analyzer("compiler_warnings")().run(context, params)


def test_clean_code_gets_full_marks(context_factory):
    assert syntax(context_factory, ADD).score == 1.0


def test_werror_counts_warnings_rather_than_failing(context_factory):
    result = syntax(context_factory, "int main(void) { int spare; return 0; }\n")
    assert result.score == 0.9
    assert result.evidence["warnings"][0]["code"] == "-Wunused-variable"


def test_compile_failure_scores_zero(context_factory):
    assert syntax(context_factory, "int main(void) { return 0 }\n").score == 0.0
