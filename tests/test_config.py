import json

import pytest

from agent.config_loader import ConfigError, load_rules, parse_rules

PROJECT_RULES = ["config/rules.json", "config/rules_sort.json"]


def parse(document):
    return parse_rules(document, "rules.json", "sha256:x")


def base(**changes):
    document = {"problem": "p", "time_limit_s": 1, "memory_limit_mb": 64,
                "metrics": [{"name": "m", "analyzer": "function_split", "weight": 1.0}]}
    document.update(changes)
    return document


@pytest.mark.parametrize("path", PROJECT_RULES)
def test_shipped_rules_are_valid(path):
    assert load_rules(path).metrics


def test_assignment_example_shape_loads():
    rules = parse(base(metrics=[
        {"name": "a", "analyzer": "compiler_warnings", "weight": 0.5,
         "params": {"flags": "-Wall -Wextra -Werror -std=c11"}},
        {"name": "b", "analyzer": "static_analysis", "weight": 0.5,
         "params": {"max_cyclomatic": 8, "max_function_length": 40}}]))
    assert rules.scoring["unavailable_policy"] == "renormalize"
    assert rules.execution["compiler"] == "gcc"


def test_missing_file():
    with pytest.raises(ConfigError, match="cannot read"):
        load_rules("/nonexistent/rules.json")


def test_invalid_json_reports_position(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"problem": ')
    with pytest.raises(ConfigError, match="not valid JSON: line 1"):
        load_rules(str(path))


def test_top_level_must_be_object():
    with pytest.raises(ConfigError, match="JSON object"):
        parse([])


@pytest.mark.parametrize("key", ["problem", "time_limit_s", "memory_limit_mb", "metrics"])
def test_missing_required_setting(key):
    document = base()
    del document[key]
    with pytest.raises(ConfigError, match=f"missing required setting '{key}'"):
        parse(document)


@pytest.mark.parametrize("weight,message", [
    (-0.1, "must not be negative"), ("high", "must be a number"), (True, "must be a number")])
def test_invalid_weights(weight, message):
    document = base(metrics=[{"name": "m", "analyzer": "function_split", "weight": weight}])
    with pytest.raises(ConfigError, match=message):
        parse(document)


def test_weights_must_sum_to_one_by_default():
    document = base(metrics=[{"name": "m", "analyzer": "function_split", "weight": 0.5}])
    with pytest.raises(ConfigError, match="sum to 0.5"):
        parse(document)


def test_weight_sum_policy_normalize_allows_other_totals():
    document = base(metrics=[{"name": "m", "analyzer": "function_split", "weight": 30}],
                    scoring={"weight_sum_policy": "normalize"})
    assert parse(document).metrics[0].weight == 30


def test_disabled_metrics_do_not_count_toward_the_sum():
    document = base(metrics=[
        {"name": "a", "analyzer": "function_split", "weight": 1.0},
        {"name": "b", "analyzer": "function_split", "weight": 0.5, "enabled": False}])
    assert len(parse(document).metrics) == 2


def test_all_zero_weights_rejected():
    document = base(metrics=[{"name": "m", "analyzer": "function_split", "weight": 0}],
                    scoring={"weight_sum_policy": "normalize"})
    with pytest.raises(ConfigError, match="above zero"):
        parse(document)


@pytest.mark.parametrize("threshold", [-0.1, 1.5, "x"])
def test_invalid_threshold(threshold):
    document = base(metrics=[{"name": "m", "analyzer": "function_split", "weight": 1,
                              "threshold": threshold}])
    with pytest.raises(ConfigError, match="threshold must be between"):
        parse(document)


def test_similarity_threshold_range_checked():
    document = base(metrics=[{"name": "m", "analyzer": "similarity_flag", "weight": 1,
                              "params": {"corpus_dir": "c", "flag_threshold": 1.5}}])
    with pytest.raises(ConfigError, match="flag_threshold must be between"):
        parse(document)


def test_unknown_analyzer_lists_alternatives():
    document = base(metrics=[{"name": "m", "analyzer": "nope", "weight": 1}])
    with pytest.raises(ConfigError, match="unknown analyzer 'nope'.*io_tests"):
        parse(document)


def test_required_param_enforced():
    document = base(metrics=[{"name": "m", "analyzer": "io_tests", "weight": 1}])
    with pytest.raises(ConfigError, match="'testset_dir' is required"):
        parse(document)


def test_unknown_param_is_caught_as_a_typo():
    document = base(metrics=[{"name": "m", "analyzer": "function_split", "weight": 1,
                              "params": {"min_funtions": 2}}])
    with pytest.raises(ConfigError, match="unknown param 'min_funtions'"):
        parse(document)


def test_unknown_setting_and_bad_choice():
    with pytest.raises(ConfigError, match="unknown setting 'execution.compilr'"):
        parse(base(execution={"compilr": "gcc"}))
    with pytest.raises(ConfigError, match="must be one of"):
        parse(base(execution={"backend": "chroot"}))


def test_duplicate_metric_names_rejected():
    document = base(metrics=[{"name": "m", "analyzer": "function_split", "weight": 0.5},
                             {"name": "m", "analyzer": "llm_review", "weight": 0.5}])
    with pytest.raises(ConfigError, match="duplicate"):
        parse(document)


def test_every_problem_is_reported_at_once():
    document = base(time_limit_s=-1, memory_limit_mb=0)
    with pytest.raises(ConfigError) as caught:
        parse(document)
    assert "time_limit_s" in str(caught.value) and "memory_limit_mb" in str(caught.value)


def test_complexity_bound_and_sizes_validated():
    bad = {"name": "m", "analyzer": "complexity_estimator", "weight": 1,
           "params": {"required": "O(fast)", "sizes": [10, 5]}}
    with pytest.raises(ConfigError) as caught:
        parse(base(metrics=[bad]))
    assert "required must be one of" in str(caught.value)
    assert "strictly increasing" in str(caught.value)


def test_paths_resolve_against_the_rules_file(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(base()))
    assert load_rules(str(path)).resolve("../x") == str(tmp_path.parent / "x")


def test_hash_tracks_content(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(base()))
    first = load_rules(str(path)).hash
    path.write_text(json.dumps(base(time_limit_s=2)))
    assert load_rules(str(path)).hash != first
