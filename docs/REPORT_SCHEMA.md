# JSON Report Schema (version 1.0)

Every report has `schema_version`. A field's meaning will not change within a major version.
Strings are capped at `report.max_text_bytes`.

## Top level

| Field | Type | Meaning |
|-------|------|---------|
| `schema_version` | string | `"1.0"` |
| `submission` | string | File name as submitted |
| `submission_id` | string | Name plus a short source hash |
| `problem` | string | From the rules |
| `source_hash`, `rules_hash` | string | `sha256:...` |
| `rules_file` | string | Rules file name |
| `testset_hash` | string or null | Hash of the test directory |
| `timestamp` | string | UTC, ISO 8601 |
| `grade` | number or null | 0 to 100; null when not gradable |
| `evaluation_status` | string | `complete`, `partial`, or `not_gradable` |
| `grade_fingerprint` | string | Equal across reproducible runs |
| `scoring` | object | See below |
| `first_pass` | object | See below |
| `compilation` | object | See below |
| `execution` | object | `name`, `isolated`, `guarantees`, `limits` |
| `metrics` | array | One entry per rule, in rule order |
| `flags` | array | See below |
| `feedback` | object | See below |
| `tool_versions` | object | `compiler`, `cppcheck`, `lizard` |
| `usefulness_limitations` | object | Optional; `usefulness[]`, `limitations[]` |

## `scoring`

`grade`, `status`, `formula`, `applicable_weight`, `total_weight`, `excluded_metrics[]`,
`zeroed_metrics[]`, and `policy` (the scoring settings in force).

## `first_pass`

`compiled`, `smoke_ok`, `smoke_ran`, `suspected_infinite_loop`, `smoke_crashed`,
`smoke_detail`, and `static_sanity` (`has_main`, `calls_reader`, `calls_writer`, `main_returns`).

## `compilation`

`success`, `compiler`, `compiler_version`, `flags[]`, `exit_code`, `output`, and
`diagnostics[]` of `{tool, severity, message, line, column, code}`.

## `metrics[]`

| Field | Meaning |
|-------|---------|
| `name`, `analyzer`, `weight` | From the rules |
| `status` | `scored`, `blocked`, `not_evaluated`, or `disabled` |
| `score` | 0 to 1, or null when there is no score |
| `contribution`, `max_contribution` | Marks earned and available, out of 100 |
| `threshold`, `met_threshold` | Optional pass mark and whether it was met |
| `feedback` | One-line verdict |
| `evidence` | Analyzer-specific raw data |
| `counterexamples[]` | See below |

**Evidence by analyzer**

| Analyzer | Main keys |
|----------|-----------|
| `io_tests` | `tests_passed`, `tests_total`, `comparison`, `status_counts`, `results[]`, `malformed_tests[]` |
| `compiler_warnings` | `flags`, `warnings[]` or `errors[]` |
| `static_analysis` | `cppcheck_findings[]`, `functions[]`, `thresholds` |
| `function_split` | `functions_defined`, `expected_min`, `names[]`, `helpers_reachable_from_main[]`, `helpers_unused[]`, `main_share_of_function_lines`, `criteria` |
| `edge_case_runner` | `cases_passed`, `cases_total`, `by_category`, `seed`, `oracle`, `unusable_cases[]` |
| `complexity_estimator` | `required`, `estimated`, `sizes[]`, `operation_counts[]`, `fit_errors`, `method`, `confidence` |
| `sanitizer_run` | `inputs_exercised`, `flags`, `diagnostics[]`, `not_freed_at_exit`, `note` |
| `llm_review` | `method`, `criteria`, `identifiers`, `comments`, `formatting`, `function_lengths[]`, `max_nesting_by_function[]`, `llm` |
| `similarity_flag` | `metric`, `comparisons`, `max_similarity`, `closest`, `threshold`, `containment_threshold`, `top_matches[]`, `style_signals_advisory[]`, `limitations` |
| `pattern_check` | `violations[]` |

`results[]` entries hold `test_id`, `status` (`passed`, `failed`, `timeout`, `crashed`,
`memory_limit`, `output_limit`), `description`, `input`, `expected`, `actual`, `stderr`,
`exit_code`, `duration_s`, `peak_memory_kb`, `comparison`, and `diagnostic`.

Durations vary between runs and are excluded from `grade_fingerprint`.

## `counterexamples[]`

`test_id`, `input`, `expected` (null when there is no reference), `got`, `why`, `origin`
(`testset` or `generated`), `category`, and `outcome`.

## `flags[]`

| `type` | Extra fields |
|--------|--------------|
| `compilation_failed` | None |
| `suspected_infinite_loop` | None |
| `smoke_crashed` | `detail` |
| `suspected_copying` | `source_kind`, `target`, `similarity`, `containment`, `note` |
| `style_signals_advisory` | `signals[]`, `note` |

## `feedback`

`where_you_failed[]` (counterexamples), `suggestions[]` of `{metric, marks_lost, text}`,
`skipped_checks[]` of `{check, status, reason}`, and `advisory_llm_remarks[]`.
