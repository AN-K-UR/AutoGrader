# AutoGrader: A Rule-Driven Automatic Evaluator for Student C Programs

AutoGrader takes a student's C file and a rules file written by the instructor, runs the
program in a sandbox, evaluates it with one analyzer per metric, and produces a single
reproducible grade with feedback. For an incorrect program, the feedback includes a specific
failing input, the expected output beside it, and an explanation.

**Contract:** same submission + same rules → same grade.

## Quick start (macOS, Apple silicon)

```bash
xcode-select --install
```

```bash
scripts/setup.sh
```

```bash
.venv/bin/python main.py grade --source submissions/examples/add_student.c --config config/rules.json --output reports/ --print-report
```

This writes `reports/add_student.json` and `reports/add_student.txt`. `scripts/run_demo.sh`
grades all 18 samples and writes [reports/samples/SUMMARY.md](reports/samples/SUMMARY.md).

## Web interface

```bash
.venv/bin/python main.py serve
```

Then open <http://127.0.0.1:8000>. Choose a rule set, pick a sample, upload a `.c` file, or paste
code, and press **Grade submission**. The page shows the grade, marks per metric, failing inputs,
suggestions, and details, and it can download both reports. Press `Ctrl+C` in Terminal to stop.

It runs the same agent as the CLI, gives the same grades, needs no internet, and listens on this
computer only. It has no login, so do not expose it to a network. See [SECURITY.md](SECURITY.md).
The assignment does not require a frontend; this is an addition.

## Problem and objectives

Marking programs by hand is slow, inconsistent, and does not scale. The assignment asks for
an agent that does the whole job unattended. It must:

1. Run submissions safely under fixed time and memory limits, surviving crashes and hangs.
2. Read rules from a file outside the code.
3. Evaluate each metric with its own analyzer and combine them using the rule weights.
4. Give an incorrect submission a failing input, the expected output, and an explanation.
5. Flag suspected copying from online sources, LLMs, or others.
6. State its usefulness and limitations, with concrete examples of each.

[docs/REQUIREMENTS_ANALYSIS.md](docs/REQUIREMENTS_ANALYSIS.md) maps each requirement to code
and tests, and lists the problems found in the assignment text.

## Features

| Metric (assignment name) | Analyzer | Method |
|--------------------------|----------|--------|
| correctness | `io_tests` | Runs the test set, compares under an explicit policy |
| syntax | `compiler_warnings` | Compile status and warning count |
| structure | `static_analysis` | Cppcheck findings plus Lizard complexity and length |
| modularity | `function_split` | Function count, helpers in use, share held by `main` |
| logical | `edge_case_runner` | Seeded corner cases checked against a reference solution |
| complexity | `complexity_estimator` | Growth fitted to exact operation counts |
| memory_safety | `sanitizer_run` | ASan, UBSan, and an allocation tracker for leaks |
| readability | `llm_review` | Deterministic checks; optional Ollama remarks are unscored |
| originality | `similarity_flag` | Normalized token shingles against a local corpus |
| (any you add) | `pattern_check` | Forbid or require calls using the rules file alone |

## Architecture and workflow

```text
submission.c + rules.json
        |
   config_loader ........ validate rules, report every problem
        |
   coordinator
     first pass ......... compile -> smoke run -> static sanity
     dispatch ........... source analyzers in parallel, execution analyzers in series
        |                         |
   score_calculator       execution backend (seatbelt / docker)
        |
   feedback_generator
        |
   json_report ---> report dict ---> text_report
```

See [ARCHITECTURE.md](ARCHITECTURE.md). The reasoning behind each choice is in
[DESIGN_DECISIONS.md](DESIGN_DECISIONS.md).

```text
AutoGrader/
├── main.py              CLI
├── agent/               coordinator, first pass, rules loading, evaluation state
├── execution/           process runner, sandbox backends, compiler, C runtime shims
├── analyzers/           one module per metric, plus shared helpers
├── scoring/             weighted score and feedback
├── reporting/           JSON and text reports
├── web/                 local web interface
├── models/              shared result dataclasses
├── config/              example rule sets, usefulness and limitations text
├── test_cases/          problem test sets
├── references/          instructor reference solutions
├── corpus/              comparison corpus for originality
├── submissions/examples/  18 sample programs
├── reports/samples/     reports from real runs
├── tests/               pytest suite
├── scripts/             setup, demo, mutation check
├── docker/              execution image
└── docs/                requirements, report schema, final-report input
```

## Prerequisites and installation

| Tool | Needed for | Install |
|------|-----------|---------|
| Python 3.9+ | The agent | Included with Xcode Command Line Tools |
| C compiler | Compiling submissions | `xcode-select --install` |
| `sandbox-exec` | Isolation on macOS | Part of macOS |
| Cppcheck, Lizard, pytest | Structure metric, tests | `pip`, through `requirements.txt` |
| Docker | Optional Linux backend | Docker Desktop |
| Ollama | Optional advisory remarks | ollama.com |

`/usr/bin/gcc` on macOS is Apple clang, and reports record the real compiler. To use GNU GCC,
set `execution.compiler` to its name, such as `gcc-14`.

Manual setup, if you prefer it to `scripts/setup.sh`:

```bash
python3 -m venv .venv
```

```bash
.venv/bin/python -m pip install -r requirements.txt
```

```bash
.venv/bin/python main.py check-tools
```

### Docker backend

The Docker backend is implemented, but Docker was not available during development, so it has
only been tested through its command construction. Check it before relying on it:

```bash
docker build -t autograder-sandbox:latest docker/
```

Then set `"execution": {"backend": "docker"}` and grade a sample. With `"backend": "auto"`
Docker is used when its image exists, and Seatbelt otherwise.

## CLI

| Command | Purpose |
|---------|---------|
| `grade --source F [--config R] [--tests D] [--output O]` | Grade one submission |
| `validate-config --config R` | Check a rules file |
| `list-tests --config R` | List test cases |
| `check-tools` | Show available tools and backends |
| `verify-repro --source F --runs N` | Grade N times and compare |
| `serve [--port P]` | Start the web interface on this computer |
| `version` | Show the version |

`grade` also takes `--print-report`, `--no-llm`, `--keep-temp`, and `--allow-unsafe`.
`--allow-unsafe` removes all isolation, is labelled in the report, and is for trusted code only.

| Exit code | Meaning |
|-----------|---------|
| 0 | Finished. A low grade is still a success |
| 1 | Internal failure |
| 2 | Invalid rules, arguments, or test directory |
| 3 | Unusable submission path |
| 4 | No secure backend available |
| 5 | `verify-repro` found a difference |

## Rules file

The shape is the assignment's. [config/rules.json](config/rules.json) is the assignment's
example rule set, and [config/rules_sort.json](config/rules_sort.json) is a second one. Paths
resolve relative to the rules file.

```json
{
  "problem": "add_two_integers",
  "time_limit_s": 1,
  "memory_limit_mb": 64,
  "metrics": [
    { "name": "correctness", "analyzer": "io_tests", "weight": 0.20, "threshold": 0.6,
      "params": { "testset_dir": "../test_cases/add/" } }
  ]
}
```

Each metric takes `name`, `analyzer`, and `weight`, plus optional `params`, `enabled`, and
`threshold`. A threshold reports whether the metric was met and does not change the grade.
Misspelled keys are errors rather than being ignored.

**Optional sections and their defaults**

| Setting | Default | Meaning |
|---------|---------|---------|
| `execution.backend` | `auto` | `auto`, `seatbelt`, `docker`, or `unsafe` |
| `execution.compiler` | `gcc` | Compiler name |
| `execution.link_flags` | `["-lm"]` | Link flags |
| `execution.compile_timeout_s` | `20` | Per-compile limit |
| `execution.max_output_bytes` | `1000000` | Output cap per stream |
| `execution.max_processes` | `16` | Process limit (Docker) |
| `execution.docker_image` | `autograder-sandbox:latest` | Execution image |
| `first_pass.compile_flags` | `-O2 -Wall -Wextra -std=c11` | Main build |
| `first_pass.smoke_input` | first test's input | Smoke-run input |
| `first_pass.fail_on_smoke_crash` | `false` | Skip execution analyzers after a smoke crash |
| `scoring.unavailable_policy` | `renormalize` | Tool missing: drop the weight, or `zero` |
| `scoring.compile_failure_policy` | `partial` | Keep source metrics, or `zero` everything |
| `scoring.weight_sum_policy` | `error` | Weights must sum to 1, or `normalize` |
| `report.max_text_bytes` | `2000` | Cap on any string in a report |
| `report.max_counterexamples` | `5` | Failures shown in feedback |
| `report.max_findings` | `25` | Counterexamples kept per metric |
| `report.include_usefulness_limitations` | `true` | Add that section to reports |

**Analyzer parameters**

| Analyzer | Parameters (required in bold) |
|----------|------------------------------|
| `io_tests` | **`testset_dir`**, `comparison`, `require_zero_exit` |
| `compiler_warnings` | `flags`, `penalty_per_warning` |
| `static_analysis` | `max_cyclomatic`, `max_function_length`, `severity_penalties` |
| `function_split` | `expect_helpers`, `min_functions`, `max_main_share`, `criteria_weights` |
| `edge_case_runner` | **`cases`**, `input_spec`, `reference_solution`, `seed`, `random_cases`, `comparison` |
| `complexity_estimator` | **`required`**, **`sizes`**, `input_template`, `seed`, `time_limit_s`, `penalty_per_class` |
| `sanitizer_run` | `flags`, `testset_dir`, `extra_inputs`, `max_inputs`, `penalties`, `check_leaks` |
| `llm_review` | `criteria_weights`, `allowed_short_names`, `lines_per_comment`, `max_function_length`, `max_nesting`, `use_llm`, `model`, `temperature`, `seed`, `llm_timeout_s`, `base_url` |
| `similarity_flag` | **`corpus_dir`**, `flag_threshold`, `containment_threshold`, `template_file`, `flagged_score`, `top_matches` |
| `pattern_check` | `forbid_calls`, `require_calls`, `forbid_keywords`, `penalty_per_violation` |

`edge_case_runner` categories are, for `{"kind": "ints"}`: negatives, zero, int_overflow,
int_boundaries, whitespace, empty_input, random. For `{"kind": "array"}`: empty_array,
single_element, duplicates, already_sorted, reverse_sorted, negatives, extreme_values,
whitespace, random. `["all"]` selects every category.

`complexity_estimator` builds inputs from `input_template`, which understands `{n}` and
`{ints:n:LOW:HIGH}`. Supported bounds are O(1), O(log n), O(n), O(n log n), O(n^2), O(n^3),
and O(2^n).

**Adding a metric.** To use an existing analyzer, add an entry to `metrics`. To add a new kind
of check, drop a module into `analyzers/` that uses `@register`. It is discovered at runtime,
with no change to the agent.

## Test-case format

Each test in a directory is `<id>.in` and `<id>.out`, with an optional `<id>.meta.json`:

```json
{ "description": "INT_MAX + 1", "time_limit_s": 2, "comparison": "exact" }
```

| Comparison | Accepts |
|------------|---------|
| `exact` | Byte-identical output |
| `trim_trailing` (default) | Trailing spaces and final newlines may differ |
| `normalize_whitespace` | All whitespace may differ |

Forgiven differences are recorded in the test's result. A test with a missing file or invalid
metadata is malformed: it is listed, not run, and neither passes nor fails.

## Scoring

```text
grade = 100 * sum(weight_i * score_i) / sum(applicable_weights)
```

| Status | Meaning | Effect |
|--------|---------|--------|
| `scored` | The analyzer ran | Score counts |
| `blocked` | The submission prevented it (no compile, hang, crash) | Scores 0 |
| `not_evaluated` | The environment prevented it (tool or corpus missing) | Weight dropped, or `zero` by policy |
| `disabled` | The rules turned it off | Not counted |

A skipped check never earns marks. If nothing could be evaluated, the grade is `null` and the
status `not_gradable`, not 0. See the worked example in
[VIVA_PREPARATION.md](VIVA_PREPARATION.md).

## Reports

JSON is for machines ([schema](docs/REPORT_SCHEMA.md)) and text is for students. The text
report is rendered from the JSON report's dictionary, so the two cannot disagree on the grade.
Text fields are capped, and absolute host paths are not included.

## Testing

```bash
.venv/bin/python -m pytest
```

Results and coverage of the suite are in [TESTING.md](TESTING.md).
`scripts/mutation_check.py` breaks critical logic on purpose to confirm the tests notice.

## Optional Ollama integration

```bash
ollama pull llama3.1
```

Nothing is downloaded automatically. With `use_llm: true`, the local model's remarks appear
in the report, labelled advisory. They never change the grade and are excluded from the
fingerprint. If Ollama, the model, or a valid reply is missing, the report records that and
grading continues. Only a loopback address is accepted, so code stays on the machine. The
prompt is in `analyzers/llm_client.py`. Ollama was not installed during development, so this
integration has only been tested against a mocked server.

To use it from the web page, start Ollama and tick **Add local LLM remarks**. The box is
disabled while Ollama is not running.

## Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| `Sandbox error: no secure execution backend` | Neither Docker nor `sandbox-exec` works here. Install Docker |
| `Configuration error: ... unknown param` | A typo in the rules file; the message lists valid names |
| `structure` shows a skipped tool | Run `scripts/setup.sh`, or install Cppcheck |
| `memory_safety` is `not_evaluated` | The compiler lacks sanitizer support; the reason is in the report |
| `sandbox-exec: ... Operation not permitted` | Running inside another restrictive sandbox |
| A correct program times out | Raise `time_limit_s` in the rules |
| `gcc` not found | Run `xcode-select --install` |
| `Address already in use` from `serve` | Use another port: `serve --port 8001` |

## Security limitations

Student code is treated as untrusted. On macOS the Seatbelt backend blocks file writes, fork,
exec, network connections, and reads of user files; these are tested. This is defence in
depth for a course setting, not a security guarantee. `sandbox-exec` is deprecated by Apple
and shares the host kernel. Read [SECURITY.md](SECURITY.md) before grading submissions you do
not trust.

## Similarity limitations

Similarity compares token structure against the local corpus only. A flag means "a person
should look", not "this was copied". Very short programs match easily, reordered code can
match poorly, and the agent cannot search the internet or identify LLM authorship. The
"online" and "llm" labels mean only that the match was with a file the instructor stored in
that folder.

## Known limitations

- Tests and sanitizers only observe what actually executes.
- Operation counts exclude time inside libc.
- Time limits measure CPU time, so load has little effect, but a program using almost exactly
  its limit can still flip between runs.
- `perf`/`oprofile` profiling is not integrated. Peak memory and operation counts are recorded
  instead.
- The grade is reproducible for a given toolchain. A different compiler version can change
  warnings, operation counts, or undefined behaviour.

The report's "Usefulness and limitations" section gives concrete wrong-verdict examples, each
demonstrated by `tests/test_limitations.py`.

## Future enhancements

Multi-file submissions; a batch mode for a whole class that compares all pairs; property-based
input generation; recording per-function operation counts; and verified Docker support.

## Project documents

[ARCHITECTURE.md](ARCHITECTURE.md) ·
[DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) ·
[TESTING.md](TESTING.md) ·
[SECURITY.md](SECURITY.md) ·
[CONTRIBUTION_GUIDE.md](CONTRIBUTION_GUIDE.md) ·
[PROJECT_DEMO.md](PROJECT_DEMO.md) ·
[VIVA_PREPARATION.md](VIVA_PREPARATION.md) ·
[docs/FINAL_REPORT_INPUT.md](docs/FINAL_REPORT_INPUT.md)
