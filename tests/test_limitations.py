"""Every limitation the report claims is demonstrated here, not just asserted.

If a future change fixes one of these, the test fails and the text must change too.
"""
import json

from agent.config_loader import load_rules
from agent.coordinator import evaluate
from analyzers.base import get_analyzer

STRLEN_LOOP = """#include <stdio.h>
#include <string.h>
static char text[20000];
int main(void) {
    int count = 0;
    if (scanf("%19999s", text) != 1) { return 1; }
    for (size_t i = 0; i < strlen(text); i++) { count += text[i] == 'a'; }
    printf("%d\\n", count);
    return 0;
}
"""
SHORT_ONE = """#include <stdio.h>
int main(void) { int p, q; scanf("%d %d", &p, &q); printf("%d\\n", p + q); return 0; }
"""
SHORT_TWO = """#include <stdio.h>
/* written independently */
int main(void) {
    int alpha, beta;
    scanf("%d %d", &alpha, &beta);
    printf("%d\\n", alpha + beta);
    return 0;
}
"""


def metric(evaluation, name):
    return next(item for item in evaluation.metrics if item.name == name)


def test_wrong_program_gets_full_marks_when_no_test_reaches_the_bug():
    evaluation = evaluate("submissions/examples/add_passes_but_wrong.c",
                          load_rules("config/rules.json"), allow_llm=False)
    assert evaluation.summary.grade == 100.0


def test_unreached_memory_bug_is_not_found():
    evaluation = evaluate("submissions/examples/add_hidden_memory_bug.c",
                          load_rules("config/rules.json"), allow_llm=False)
    assert metric(evaluation, "memory_safety").result.score == 1.0


def test_hidden_quadratic_cost_in_libc_is_reported_as_linear(context_factory, monkeypatch):
    params = {"required": "O(n)", "sizes": [100, 200, 400, 800, 1600]}
    context = context_factory(STRLEN_LOOP, [{"name": "t", "analyzer": "complexity_estimator",
                                             "weight": 1.0, "params": params}])
    # Input templates cannot express a string of n letters, so supply one directly.
    monkeypatch.setattr("analyzers.complexity.render_input",
                        lambda template, size, generator: "a" * size + "\n")
    result = get_analyzer("complexity_estimator")().run(context, params)
    assert result.evidence["estimated"] == "O(n)"


def test_independent_short_solutions_are_falsely_flagged(context_factory, tmp_path):
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "other.c").write_text(SHORT_TWO)
    params = {"corpus_dir": "corpus"}
    context = context_factory(SHORT_ONE, [{"name": "o", "analyzer": "similarity_flag",
                                           "weight": 1.0, "params": params}], compile_it=False)
    result = get_analyzer("similarity_flag")().run(context, params)
    assert result.evidence["max_similarity"] == 1.0
    assert result.flags[0]["type"] == "suspected_copying"


def test_structural_rewrite_is_not_flagged(context_factory, tmp_path):
    rewrite = """#include <stdio.h>
static int read_pair(int *left, int *right) { return scanf("%d %d", left, right); }
static int combine(int left, int right) { return left + right; }
int main(void) {
    int one = 0, two = 0;
    if (read_pair(&one, &two) == 2) { printf("%d\\n", combine(one, two)); }
    return 0;
}
"""
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "other.c").write_text(SHORT_TWO)
    params = {"corpus_dir": "corpus"}
    context = context_factory(rewrite, [{"name": "o", "analyzer": "similarity_flag",
                                         "weight": 1.0, "params": params}], compile_it=False)
    result = get_analyzer("similarity_flag")().run(context, params)
    assert result.evidence["max_similarity"] < 0.85 and not result.flags


def test_report_contains_each_demonstrated_limitation():
    with open("config/usefulness_limitations.json", encoding="utf-8") as handle:
        block = json.load(handle)
    text = json.dumps(block)
    for marker in ("add_passes_but_wrong.c", "add_hidden_memory_bug.c", "strlen", "1.00"):
        assert marker in text
