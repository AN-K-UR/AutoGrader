"""Analyzers that never run the submission."""
import unittest.mock as mock

import pytest

from analyzers.base import get_analyzer
from analyzers.c_source import CSource
from analyzers.complexity import estimate_growth, render_input
from analyzers.originality import jaccard, normalize_tokens, shingles, style_signals
from analyzers.readability import comment_score, formatting_score, identifier_score
from analyzers.static_analysis import parse_cppcheck_xml, run_cppcheck, run_lizard, find_tool
from agent.first_pass import static_sanity
from models.results import MetricStatus
import random

GOOD = """/* Adds two numbers. */
#include <stdio.h>

/* Returns the sum. */
static int add_numbers(int first, int second) {
    return first + second;
}

int main(void) {
    int left_value = 2;
    int right_value = 3;
    printf("%d\\n", add_numbers(left_value, right_value));
    return 0;
}
"""
ONLY_MAIN = 'int main(void) { return 0; }\n'
UNCALLED = """static int spare(void) { return spare(); }
int main(void) { return 0; }
"""
CRAMPED = 'int main(){int a,b;a=1;b=2;if(a==b){a=b+1;}return a;}\n'


def metric(name, analyzer, params=None):
    return [{"name": name, "analyzer": analyzer, "weight": 1.0, "params": params or {}}]


def run(context_factory, source, analyzer, params=None):
    context = context_factory(source, metric("m", analyzer, params), compile_it=False)
    return get_analyzer(analyzer)().run(context, params or {})


# Lexer ---------------------------------------------------------------------

def test_comments_and_strings_are_not_code():
    source = CSource('// printf("a");\nint main(void) { char *s = "scanf("; return 0; }\n')
    assert source.called_names() == set()
    assert len(source.comments) == 1


def test_functions_are_found_with_lines_and_parameters():
    source = CSource(GOOD)
    helper = source.function("add_numbers")
    assert helper.parameters == 2 and helper.start_line == 5 and helper.end_line == 7
    assert source.function("main").parameters == 0


def test_control_statements_are_not_functions():
    source = CSource("int main(void) { if (1) { while (0) { } } return 0; }")
    assert [item.name for item in source.functions] == ["main"]
    assert source.function("main").max_nesting == 2


def test_multiline_comment_keeps_line_numbers():
    source = CSource("/* one\ntwo\nthree */\nint main(void) { return 0; }\n")
    assert source.function("main").start_line == 4


def test_static_sanity_ignores_comments():
    sanity = static_sanity(CSource('int main(void) { /* printf("x"); */ }\n'))
    assert sanity == {"has_main": True, "calls_reader": False, "calls_writer": False,
                      "main_returns": False}


# Modularity ----------------------------------------------------------------

def test_only_main_scores_low_and_says_so(context_factory):
    result = run(context_factory, ONLY_MAIN, "function_split", {"min_functions": 2})
    assert result.score == 0.25
    assert result.evidence["functions_defined"] == 1
    assert "Only main()" in result.feedback
    assert any("Extract a helper" in text for text in result.suggestions)


def test_helper_in_use_scores_well(context_factory):
    result = run(context_factory, GOOD, "function_split")
    assert result.score > 0.9
    assert result.evidence["helpers_reachable_from_main"] == ["add_numbers"]


def test_uncalled_helper_is_not_credit(context_factory):
    result = run(context_factory, UNCALLED, "function_split")
    assert result.evidence["helpers_unused"] == ["spare"]
    assert result.score < 0.8


def test_helpers_not_expected(context_factory):
    result = run(context_factory, ONLY_MAIN, "function_split", {"expect_helpers": False})
    assert result.score == 1.0


def test_no_functions_at_all(context_factory):
    assert run(context_factory, "int x;\n", "function_split").score == 0.0


# Readability ---------------------------------------------------------------

def test_terse_names_are_named_as_evidence():
    score, evidence = identifier_score(CSource(CRAMPED), ("i",))
    assert evidence["short_names"] == ["a", "b"]
    assert score < 1


def test_loop_counters_are_allowed():
    source = CSource("int main(void) { for (int i = 0; i < 3; i++) { } return 0; }")
    assert identifier_score(source, ("i",))[1]["short_names"] == []


def test_short_program_without_comments_is_neutral_not_failing():
    assert comment_score(CSource(GOOD.replace("/* Adds two numbers. */\n", "")
                                 .replace("/* Returns the sum. */\n", "")), 25)[0] == 0.5


def test_long_uncommented_program_scores_low():
    body = "int v;\n" * 60
    assert comment_score(CSource(body), 25)[0] == 0.0


def test_formatting_evidence_names_lines():
    _, evidence = formatting_score(CSource(CRAMPED))
    assert evidence["multiple_statements"] == [1]
    assert evidence["cramped_operators"] == [1]


def test_for_loop_semicolons_are_not_multiple_statements():
    source = CSource("int main(void) {\n    for (int i = 0; i < 3; i++) {\n    }\n    return 0;\n}\n")
    assert formatting_score(source)[1]["multiple_statements"] == []


def test_unindented_body_detected():
    source = CSource("int main(void) {\nreturn 0;\n}\n")
    assert formatting_score(source)[1]["unindented"] == [2]


def test_strings_do_not_trigger_operator_spacing():
    source = CSource('#include <stdio.h>\nint main(void) {\n    puts("a=b+c");\n    return 0;\n}\n')
    assert formatting_score(source)[1]["cramped_operators"] == []


def test_readability_is_deterministic_and_never_calls_the_model(context_factory):
    with mock.patch("analyzers.readability.review_source") as model:
        first = run(context_factory, GOOD, "llm_review")
        second = run(context_factory, GOOD, "llm_review")
    model.assert_not_called()
    assert first.score == second.score
    assert first.evidence["llm"]["status"] == "disabled"


def test_readability_gives_specific_suggestions(context_factory):
    result = run(context_factory, CRAMPED, "llm_review")
    text = " ".join(result.suggestions)
    assert "a, b" in text and "one statement" in text and "spaces around operators" in text


def test_model_output_cannot_change_the_score(context_factory):
    context = context_factory(GOOD, metric("m", "llm_review"), compile_it=False)
    analyzer = get_analyzer("llm_review")()
    plain = analyzer.run(context, {"use_llm": False}).score
    reply = {"status": "ok", "advisory_score": 0, "reasons": ["bad"]}
    with mock.patch("analyzers.readability.review_source", return_value=reply):
        assert analyzer.run(context, {"use_llm": True}).score == plain


# Originality ---------------------------------------------------------------

def corpus(tmp_path, files):
    root = tmp_path / "corpus"
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return "corpus"


def test_renaming_and_comments_do_not_hide_identity():
    original = CSource("int total(int a) { return a + 1; } /* note */")
    renamed = CSource("int sum_up(int value) {\n  // other\n  return value + 2;\n}")
    assert normalize_tokens(original) == normalize_tokens(renamed)


def test_shared_keywords_alone_are_not_similarity():
    first = shingles(normalize_tokens(CSource("int main(void) { int a; a = 1; return a; }")))
    second = shingles(normalize_tokens(CSource(
        "void go(void) { while (1) { if (x > 2) { break; } } }")))
    assert jaccard(first, second) < 0.1


def test_identical_source_scores_one(context_factory, tmp_path):
    directory = corpus(tmp_path, {"peers/twin.c": GOOD})
    result = run(context_factory, GOOD, "similarity_flag", {"corpus_dir": directory})
    assert result.evidence["max_similarity"] == 1.0
    assert result.flags[0]["type"] == "suspected_copying"
    assert "does not prove" in result.flags[0]["note"]
    assert result.score == 0.5


def test_different_source_is_not_flagged(context_factory, tmp_path):
    other = "void walk(int *p, int n) { while (n-- > 0) { p[n] *= 2; if (p[n] > 9) { break; } } }"
    directory = corpus(tmp_path, {"peers/other.c": other})
    result = run(context_factory, GOOD, "similarity_flag", {"corpus_dir": directory})
    assert result.evidence["max_similarity"] < 0.3
    assert result.score == 1.0 and not result.flags


def test_missing_corpus_is_not_evaluated(context_factory):
    result = run(context_factory, GOOD, "similarity_flag", {"corpus_dir": "absent"})
    assert result.status == MetricStatus.NOT_EVALUATED
    assert result.score is None


def test_empty_corpus_is_not_evaluated(context_factory, tmp_path):
    (tmp_path / "empty").mkdir()
    result = run(context_factory, GOOD, "similarity_flag", {"corpus_dir": "empty"})
    assert result.status == MetricStatus.NOT_EVALUATED


def test_submission_does_not_match_itself(context_factory, tmp_path):
    directory = corpus(tmp_path, {"peers/mine.c": GOOD})
    context = context_factory(GOOD, metric("m", "similarity_flag", {"corpus_dir": directory}),
                              compile_it=False)
    context.original_path = str(tmp_path / "corpus" / "peers" / "mine.c")
    result = get_analyzer("similarity_flag")().run(context, {"corpus_dir": directory})
    assert result.status == MetricStatus.NOT_EVALUATED


def test_corpus_folder_labels_the_source_kind(context_factory, tmp_path):
    directory = corpus(tmp_path, {"llm/made.c": GOOD})
    result = run(context_factory, GOOD, "similarity_flag", {"corpus_dir": directory})
    assert result.flags[0]["source_kind"] == "llm"


def test_starter_code_can_be_excluded(context_factory, tmp_path):
    (tmp_path / "starter.c").write_text(GOOD)
    directory = corpus(tmp_path, {"peers/twin.c": GOOD})
    result = run(context_factory, GOOD, "similarity_flag",
                 {"corpus_dir": directory, "template_file": "starter.c"})
    assert not any(flag["type"] == "suspected_copying" for flag in result.flags)


def test_threshold_is_configurable(context_factory, tmp_path):
    near = GOOD.replace("return first + second;", "int unused = 1; return first + second;")
    directory = corpus(tmp_path, {"peers/near.c": near})
    params = {"corpus_dir": directory, "flag_threshold": 0.99, "containment_threshold": 1.0}
    assert run(context_factory, GOOD, "similarity_flag", params).score == 1.0


def test_style_signals_are_advisory_only(context_factory, tmp_path):
    chatty = ("/* Step 1: read. Time complexity: O(1). This function adds. Edge case: 0. */\n"
              + GOOD)
    assert len(style_signals(CSource(chatty))) >= 3
    other = "void walk(int *p, int n) { while (n-- > 0) { p[n] *= 2; } }"
    directory = corpus(tmp_path, {"peers/other.c": other})
    result = run(context_factory, chatty, "similarity_flag", {"corpus_dir": directory})
    assert result.score == 1.0
    assert [flag["type"] for flag in result.flags] == ["style_signals_advisory"]


# Static analysis -----------------------------------------------------------

def test_parse_cppcheck_xml():
    xml = """<?xml version="1.0"?><results version="2"><errors>
    <error id="arrayIndexOutOfBounds" severity="error" msg="Out of bounds">
    <location file="s.c" line="7"/></error>
    <error id="checkersReport" severity="information" msg="skip"/></errors></results>"""
    finding = parse_cppcheck_xml(xml)
    assert len(finding) == 1
    assert (finding[0].severity, finding[0].line, finding[0].code) == (
        "error", 7, "arrayIndexOutOfBounds")


def test_malformed_cppcheck_output_gives_no_findings():
    assert parse_cppcheck_xml("not xml") == []


@pytest.mark.cppcheck
@pytest.mark.skipif(find_tool("cppcheck") is None, reason="cppcheck not installed")
def test_real_cppcheck_finds_an_out_of_bounds_write(tmp_path):
    path = tmp_path / "s.c"
    path.write_text("int main(void) { int a[2]; a[5] = 1; return a[0]; }\n")
    findings, _ = run_cppcheck(str(path))
    assert any(item.code == "arrayIndexOutOfBounds" for item in findings)


def test_lizard_reports_function_metrics():
    functions, _ = run_lizard("s.c", GOOD)
    assert {item["name"] for item in functions} == {"add_numbers", "main"}
    assert all(item["cyclomatic"] == 1 for item in functions)


def test_cyclomatic_threshold_is_applied(context_factory):
    branches = "".join(f"    if (v == {i}) {{ return {i}; }}\n" for i in range(12))
    source = f"int pick(int v) {{\n{branches}    return 0;\n}}\nint main(void) {{ return pick(1); }}\n"
    result = run(context_factory, source, "static_analysis", {"max_cyclomatic": 5})
    assert any("cyclomatic complexity 13" in text for text in result.suggestions)
    assert result.score < 1


def test_missing_cppcheck_is_recorded_not_faked(context_factory):
    with mock.patch("analyzers.static_analysis.find_tool", return_value=None):
        result = run(context_factory, GOOD, "static_analysis")
    assert result.status == MetricStatus.SCORED
    assert result.skipped_tools[0]["tool"] == "cppcheck"
    assert "cppcheck_findings" not in result.evidence


def test_no_static_tools_is_not_evaluated(context_factory):
    with mock.patch("analyzers.static_analysis.find_tool", return_value=None), \
            mock.patch("analyzers.static_analysis.run_lizard",
                       return_value=(None, "lizard is not installed")):
        result = run(context_factory, GOOD, "static_analysis")
    assert result.status == MetricStatus.NOT_EVALUATED
    assert result.score is None


# Rules-only metric ---------------------------------------------------------

def test_pattern_check_flags_real_calls_only(context_factory):
    source = '#include <stdio.h>\n/* gets(x) */\nint main(void) { puts("gets("); return 0; }\n'
    result = run(context_factory, source, "pattern_check", {"forbid_calls": ["gets"]})
    assert result.score == 1.0
    result = run(context_factory, source, "pattern_check", {"forbid_calls": ["puts"]})
    assert result.evidence["violations"][0]["line"] == 3


def test_pattern_check_required_call(context_factory):
    result = run(context_factory, ONLY_MAIN, "pattern_check",
                 {"require_calls": ["fgets"], "penalty_per_violation": 1.0})
    assert result.score == 0.0


# Growth fitting ------------------------------------------------------------

SIZES = [100, 200, 400, 800, 1600, 3200]


@pytest.mark.parametrize("expected,shape", [
    ("O(1)", lambda n: 50),
    ("O(n)", lambda n: 7 * n + 20),
    ("O(n^2)", lambda n: 3 * n * n + 5 * n + 9),
    ("O(n^3)", lambda n: n ** 3),
])
def test_growth_classes_recovered(expected, shape):
    assert estimate_growth(SIZES, [shape(n) for n in SIZES])[0] == expected


def test_n_log_n_recovered():
    import math
    assert estimate_growth(SIZES, [int(9 * n * math.log2(n)) for n in SIZES])[0] == "O(n log n)"


def test_log_n_recovered():
    import math
    assert estimate_growth(SIZES, [int(500 * math.log2(n)) + 10 for n in SIZES])[0] == "O(log n)"


def test_exponential_recovered():
    sizes = [2, 4, 6, 8, 10, 12]
    assert estimate_growth(sizes, [2 ** n for n in sizes])[0] == "O(2^n)"


def test_input_template_is_seeded():
    first = render_input("{n}\n{ints:n:0:9}\n", 5, random.Random(1))
    second = render_input("{n}\n{ints:n:0:9}\n", 5, random.Random(1))
    assert first == second
    assert first.startswith("5\n") and len(first.split()) == 6
