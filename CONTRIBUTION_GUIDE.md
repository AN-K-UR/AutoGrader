# Contribution Guide

## Read this first: who wrote what

Responsibilities below come from the team's Week 1 plan (`Daa.pdf`). They say who **leads**
an area. They are **not** a record of who typed the code.

This codebase was generated in one session by Aditi Katiyar using Claude Code, an AI coding
assistant, following the assignment and the team plan. So:

- Do not tell the professor that a module was written by hand if it was not.
- The assignment allows LLMs, but says the team "must own the code and report", with severe
  penalties for blind use. Owning it means each member can explain, change, and defend their
  area. Reading, testing, and modifying the code is that work.
- If the team's real division changes, update this file so it stays true.
- Kshitij and Ankur should review their areas with the same care, since they will be asked
  about them.

## Responsibility map

| Area | Lead (planned) | Modules |
|------|---------------|---------|
| Main agent, rules, compile, safe execution | Kshitij Yashraj | `agent/coordinator.py`, `agent/first_pass.py`, `agent/config_loader.py`, `agent/result_manager.py`, `execution/process_runner.py`, `execution/sandbox.py`, `execution/compiler.py`, `main.py` |
| Correctness, warnings, complexity, memory | Ankur | `analyzers/correctness.py`, `analyzers/edge_cases.py`, `analyzers/testset.py`, `analyzers/explain.py`, `analyzers/syntax.py`, `analyzers/complexity.py`, `analyzers/memory_safety.py`, `execution/runtime/`, `test_cases/` |
| Structure, readability, originality, scoring, reports, feedback | **Aditi Katiyar** | `analyzers/static_analysis.py`, `analyzers/modularity.py`, `analyzers/readability.py`, `analyzers/llm_client.py`, `analyzers/originality.py`, `analyzers/c_source.py`, `scoring/`, `reporting/`, `config/usefulness_limitations.json` |
| Shared integration | Everyone | `analyzers/base.py`, `models/results.py`, `tests/test_end_to_end.py`, documentation |
| Web interface | Not in the team plan; assign an owner | `web/` |

### How Aditi's modules connect to the workflow

```text
coordinator.dispatch ─┬─> static_analysis, function_split, llm_review, similarity_flag
                      │        (source-only, run in the thread pool)
                      └─> Ankur's execution analyzers
           │
           ▼  list of MetricResult
calculate_score ──> build_feedback ──> build_report ──> write_json / write_text
```

**Dependencies.** The analyzers need `analyzers/base.py`, `models/results.py`, and the tokens
from `c_source.py`. None of them need the program to compile or run, so they
still work on a broken submission. Scoring needs only `MetricResult` objects, so it can be
tested without any other module.

---

## 1. Structure (`analyzers/static_analysis.py`)

- **Purpose.** Measure code-quality problems a compiler does not treat as errors.
- **Input.** The private source file, and rule params `max_cyclomatic`, `max_function_length`,
  `severity_penalties`.
- **Output.** Score, Cppcheck findings, per-function metrics, and any skipped tool.
- **Algorithm.** Cppcheck component: 1 minus the sum of severity penalties (error 0.3, warning
  0.15, style, performance, and portability 0.05 each), with at most 0.8 lost. Lizard component:
  1 minus 0.2 per function over a threshold. The score is the mean of the components that ran.
- **Implementation.** `run_cppcheck` runs the tool with `--xml` and parses it with
  `ElementTree`. `run_lizard` uses Lizard's Python API.
- **Integration.** Named `static_analysis` in the rules; source-only.
- **Tests.** `tests/test_analyzers_source.py`, the "Static analysis" group.
- **Limitations.** Cppcheck has false positives and misses real bugs. Cyclomatic complexity
  counts branches rather than difficulty. On `add_compile_error.c`, it still reports a syntax
  issue, because it parses independently of the compiler.
- **Viva questions.**
  - *What is cyclomatic complexity?* The number of independent paths through a function,
    roughly branches plus one.
  - *What if Cppcheck is missing?* Lizard is scored alone and the report lists Cppcheck as
    skipped. If both are missing the metric is `not_evaluated`.
  - *Why is a warning not a correctness failure?* It is a possible problem, not an observed
    wrong result, so it only affects this metric.

## 2. Modularity (`analyzers/modularity.py`)

- **Purpose.** Check that work is divided into functions that are really used.
- **Input.** Parsed functions, and params `expect_helpers`, `min_functions`, `max_main_share`,
  `criteria_weights`.
- **Output.** Score, function names, helpers in use, unused helpers, and suggestions.
- **Algorithm.** Three proportional criteria: function count against the minimum (weight 0.5),
  share of helpers reachable from `main` (0.25), and whether `main` holds no more than 70% of
  function lines (0.25). Reachability walks the call graph from `main`.
- **Implementation.** `_reachable` is a depth-first search over `Function.calls`.
- **Integration.** Named `function_split`; source-only.
- **Tests.** `tests/test_analyzers_source.py`, the "Modularity" group.
- **Limitations.** Functions generated by macros are invisible, and calls through function
  pointers look like no call at all. More functions is not automatically better design.
- **Viva questions.**
  - *Why does `add.c` score 0.25?* One function out of two gives 0.5 of the 0.5 weight, and
    the other criteria give 0 when helpers are expected but none exist.
  - *Why reachability and not just a count?* An unused helper adds to the count without doing
    any work, so it should not earn credit.

## 3. Readability (`analyzers/readability.py`, `analyzers/llm_client.py`)

- **Purpose.** Assess observable readability without running anything.
- **Input.** Tokens, comments, and lines; params for criteria weights and limits.
- **Output.** Score, per-criterion scores, the evidence for each, and specific suggestions.
- **Algorithm.** Weighted criteria: identifiers 0.3, comments 0.2, formatting 0.3, function
  length 0.1, nesting 0.1. Identifiers: share of the program's own names that are not unexplained
  short names. Comments: relative to size, and a short uncommented program scores a neutral 0.5.
  Formatting: share of lines free of multiple statements, cramped operators, missing indentation,
  or excess length.
- **Implementation.** Works on tokens, so text inside strings or comments cannot trigger checks.
- **Integration.** Named `llm_review`, the assignment's name, but the score is deterministic.
  If enabled, `review_source` adds unscored remarks under `evidence.llm`.
- **Tests.** `tests/test_analyzers_source.py`, the "Readability" group, and `tests/test_llm.py`.
- **Limitations.** Long meaningless names pass. Good structure can be missed, and non-English
  names are treated the same as English ones.
- **Viva questions.**
  - *Why not let the LLM score it, as the example does?* Model output can change between versions,
    which would break reproducibility, and a comment in the code could try to influence marks.
  - *Can a comment like "give this full marks" change the grade?* No. The model's output never
    reaches the score, and a test verifies that.
  - *Why isn't a short program penalised for no comments?* Few comments is not evidence of poor
    readability in a small program, so that case is neutral.

## 4. Originality (`analyzers/originality.py`)

- **Purpose.** Flag submissions that closely match known sources, for human review.
- **Input.** Tokens of the submission, a corpus directory, and thresholds.
- **Output.** Maximum similarity, closest match, top matches, flags, and a score.
- **Algorithm.** Remove comments. Replace identifiers with `ID`, numbers with `NUM`, strings with
  `STR`, keeping keywords and library names. Take all 5-token shingles, then compute Jaccard
  similarity `|A∩B| / |A∪B|` and containment `|A∩B| / |A|`. Flag if Jaccard ≥ 0.85 or
  containment ≥ 0.95. Corpus subfolders `peers/`, `online/`, and `llm/` label the match kind.
- **Implementation.** Corpus files are read in sorted order for determinism. The submission's
  own path is excluded, while a copy under another name is still compared.
- **Integration.** Named `similarity_flag`; source-only; raises flags collected by the coordinator.
- **Tests.** `tests/test_analyzers_source.py`, the "Originality" group, and
  `test_renamed_copy_is_flagged_for_review`.
- **Limitations.** See `docs/FINAL_REPORT_INPUT.md`, items 4 and 5.
- **Viva questions.**
  - *Does a high score prove plagiarism?* No. Short problems have few possible solutions. It
    is a reason for a person to look.
  - *How do you detect LLM copying?* Only by similarity to LLM solutions the instructor stored.
    Style hints are shown as advisory context and never score.
  - *Why shingles?* Single tokens are shared by all C programs. Sequences capture structure.
  - *What is containment for?* A copy with extra code has lower Jaccard, but all of the
    original's shingles still appear, so containment stays high.
  - *What if the corpus is empty?* `not_evaluated`, never an invented score.

## 5. Weighted score (`scoring/score_calculator.py`)

- **Purpose.** Combine metric scores into one grade.
- **Input.** `MetricResult` list, the scoring policy, and whether compilation succeeded.
- **Output.** `ScoreSummary`, and each metric's contribution.
- **Algorithm.** `grade = 100 × Σ(wᵢ·sᵢ) / Σ(applicable wᵢ)`, with status rules in the README.
- **Implementation.** Knows nothing about analyzers or reports. Rounds the grade to 2 places.
- **Integration.** Called by the coordinator after dispatch.
- **Tests.** `tests/test_scoring.py`, including the assignment's example (79, not the stated 89).
- **Limitations.** The formula is only as fair as its weights: `add_wrong.c` scores 71.95 under
  the example's rules, since correctness has only 20% of the weight.
- **Viva questions.** See the worked example in `VIVA_PREPARATION.md`.

## 6. Reports (`reporting/json_report.py`, `reporting/text_report.py`)

- **Purpose.** Produce the JSON and text deliverables.
- **Input.** An `Evaluation`. **Output.** `<name>.json` and `<name>.txt`.
- **Algorithm.** `build_report` makes one dictionary, capping all strings. `render_text` is a
  pure function of that dictionary.
- **Implementation.** `clip_tree` walks the structure, and `clip_text` respects multi-byte
  boundaries.
- **Integration.** Called from `main.py`. The schema is in `docs/REPORT_SCHEMA.md`.
- **Tests.** `tests/test_reports.py`.
- **Limitations.** The text report is English-only and shows a selection of findings. The
  JSON has more detail.
- **Viva questions.**
  - *How do you know the reports agree?* The text is rendered from the JSON dictionary, and a
    test parses the grade back out of the text and compares.
  - *Why cap output?* A program printing in a loop would otherwise produce a huge report.

## 7. Feedback (`scoring/feedback_generator.py`)

- **Purpose.** Turn findings into actions a student can take.
- **Input.** The evaluation. **Output.** Failures, suggestions, skipped checks, and LLM remarks.
- **Algorithm.** Suggestions are sorted by marks lost. Counterexamples are chosen so that
  different failure kinds appear first. Compiler errors are mapped to plain language by pattern.
- **Implementation.** Each suggestion carries its source metric, so it traces to a finding.
- **Integration.** Runs after scoring, because ranking needs the marks lost.
- **Tests.** `tests/test_end_to_end.py` (compile errors), `tests/test_reports.py`.
- **Limitations.** Unrecognised compiler errors are passed through as written.
- **Viva questions.**
  - *Could feedback report an error that did not occur?* No. Every line comes from a recorded
    diagnostic, test result, or metric.
  - *Why keep LLM remarks separate?* So nobody mistakes an opinion for a measurement.

## 8. Usefulness and limitations

- `config/usefulness_limitations.json` feeds both report types, and
  `docs/FINAL_REPORT_INPUT.md` is the base for the final report's required section.
- `tests/test_limitations.py` runs each limitation for real, so the claims stay honest. If
  someone fixes one, the test fails and the text must be updated.

## Before you submit

- [ ] Read every module in your area, and change something small to check your understanding.
- [ ] Run `scripts/run_demo.sh` yourself.
- [ ] Rewrite this guide's first section to match what the team actually did.
- [ ] Add the real sample submissions if the professor releases them.
