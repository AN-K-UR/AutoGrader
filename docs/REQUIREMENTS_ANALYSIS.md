# Requirements Analysis and Traceability

**Sources, in priority order**

1. `Agentic-AI-assignment.pdf` — the professor's assignment (primary source of truth).
2. `Daa.pdf` — the team's Week 1 plan (team members and responsibilities).
3. The project brief given to the coding assistant (technology choices, documentation list).

`Example.tgz` was fetched from the course URL. It holds a Node.js/Ollama demo project
(`depsentry`), **not** sample C submissions. The assignment's "sample submissions provided"
were therefore not available, so `submissions/examples/` is written by this project.
**Action for the team:** when the real samples are released, run the agent on them.

## 1. What the assignment requires

| ID | Requirement (assignment wording, condensed) | Class |
|----|---------------------------------------------|-------|
| R1 | Run a submission safely under fixed time and memory limits; survive crashes and non-termination | Mandatory |
| R2 | Read rules from a file outside the code: which metrics, threshold and weight for each | Mandatory |
| R3 | Each metric has its own analyzer, coordinated by the agent; the metric set is open | Mandatory |
| R4 | Run end to end unattended; one reproducible grade plus feedback | Mandatory |
| R5 | For incorrect code: a specific failing input, expected output beside it, an explanation; generate counter test cases; consider all corner cases | Mandatory |
| R6 | State usefulness and limitations, 3–4 examples each; every limitation names a concrete case with a wrong/unreliable verdict | Mandatory |
| R7 | Contract: same submission + same rules → same grade | Mandatory |
| R8 | Flag suspected copying from online resources, LLMs, or others | Mandatory |
| R9 | Weighted combination using the weights the rules specify | Mandatory |
| R10 | Example rule set, editable without touching code | Mandatory |
| R11 | Agent output on the sample submissions | Mandatory (samples unavailable, see above) |
| R12 | Reports: JSON for machines, text for students (example `reports/add.json`, `reports/add.txt`) | Illustrated by the example |
| R13 | First pass: compile check, smoke run, static sanity; on smoke timeout set `suspected_infinite_loop`, skip execution analyzers, run source-only ones, emit a partial report | Illustrated by the example |
| R14 | Dispatch analyzers "in parallel where possible" | Illustrated by the example |
| R15 | Memory-leak highlights (valgrind/ASan) | Optional ("can highlight") |
| R16 | Profiling (oprofile/perf) | Optional ("may consider") |
| R17 | Final report, GitHub link with install guide, 15–20 minute YouTube video | Mandatory — **team task** |
| R18 | LLMs may be used, but the team must own code and report; blind use is penalised | Mandatory — **team task** |

Tools named by the assignment are suggestions ("you need not build everything from scratch").
Technology such as Python, pytest, Cppcheck and Lizard comes from the project brief or the
example, not from an assignment mandate. Docker is **not** mentioned by the assignment.

## 2. Team responsibilities (from `Daa.pdf`)

| Member | Roll No. | Planned lead area |
|--------|----------|-------------------|
| Kshitij Yashraj | 2611AI38 | Main agent, rules handling, compilation, controlled execution, crash/timeout handling, coordinating analyzers |
| Ankur | 2611AI31 | Correctness runner, test cases, output comparison, compiler warnings, complexity estimation, memory safety, testing bad submissions |
| Aditi Katiyar | 2611AI18 | Structure and modularity, readability, originality, weighted score, text and JSON reports, feedback, usefulness and limitations |

Integration and final testing are joint. A separate unattached file, `agentic01-7.pdf`, is a
four-member template with placeholder names; `Daa.pdf` is the attached, named plan and is used here.

## 3. Traceability

"Verified by" names the automated tests. Results are in [TESTING.md](../TESTING.md).

| ID | Module | Verified by |
|----|--------|-------------|
| R1 | `execution/process_runner.py`, `execution/sandbox.py`, `execution/compiler.py` | `tests/test_process_runner.py`, `tests/test_sandbox.py` |
| R2 | `agent/config_loader.py`, `config/*.json` | `tests/test_config.py` |
| R3 | `analyzers/` (auto-discovered registry), `analyzers/pattern_check.py` as a rules-only new metric | `tests/test_analyzers_source.py`, `tests/test_analyzers_exec.py` |
| R4 | `main.py`, `agent/coordinator.py` | `tests/test_end_to_end.py` |
| R5 | `analyzers/correctness.py`, `analyzers/edge_cases.py`, `analyzers/explain.py` | `tests/test_analyzers_exec.py`, `tests/test_explain.py` |
| R6 | `config/usefulness_limitations.json`, `reporting/`, `docs/FINAL_REPORT_INPUT.md` | `tests/test_limitations.py`, `tests/test_reports.py` |
| R7 | Operation counts instead of timing, serial execution, `verify-repro` command, `grade_fingerprint` | `tests/test_end_to_end.py` |
| R8 | `analyzers/originality.py` | `tests/test_analyzers_source.py`, `tests/test_end_to_end.py` |
| R9 | `scoring/score_calculator.py` | `tests/test_scoring.py` |
| R10 | `config/rules.json`, `config/rules_sort.json` | `tests/test_config.py` |
| R11 | `reports/samples/`, `scripts/run_demo.sh` | Generated by real runs |
| R12 | `reporting/json_report.py`, `reporting/text_report.py` | `tests/test_reports.py` |
| R13 | `agent/first_pass.py` | `tests/test_end_to_end.py` |
| R14 | `agent/coordinator.py` (source-only analyzers in a thread pool) | `tests/test_end_to_end.py` |
| R15 | `analyzers/memory_safety.py`, `execution/runtime/leak_shim.c` | `tests/test_analyzers_exec.py` |
| R16 | Partial: peak memory and operation counts are recorded; `perf`/`oprofile` are Linux-only and not integrated | n/a |

Additions beyond the assignment: the web interface (`web/`) was requested by the team and is not
an assignment requirement.

## 4. Problems found in the assignment text

These are recorded rather than silently resolved. **Worth raising with the professor.**

| # | Issue | Decision |
|---|-------|----------|
| C1 | **The worked example does not add up.** `18+9+6+3+8+10+10+5+10 = 79`, but the text, JSON, and report all state **89**. | The agent computes the sum. It does not try to reproduce 89. |
| C2 | The example reports `-Wunused-parameter`, but `add.c` has `int main()` with no parameters, so that warning cannot occur. | The agent reports what the compiler actually emits. |
| C3 | The example test expects `-2147483648` for `INT_MAX + 1`, which is undefined behaviour in C, yet its own advice says to use `long long` (which prints `2147483648`). | The reference solution uses `long long`, matching the advice. A rule author can change the expected file. |
| C4 | `memory_safety` shows 10/10 "no diagnostics" while the same example says UBSan reported signed overflow. | The sanitizer runs on the test inputs, so an overflow test produces a real diagnostic and a deduction. |
| C5 | The tools section names Ollama (`llama3.1`), but the example uses Groq's `llama-3.3-70b-versatile`. | Local Ollama only, so source code never leaves the machine. The rule file uses `llama3.1`. |
| C6 | A score from an LLM conflicts with R7 and with the brief's "scoring must not depend on a language model". | Readability is scored deterministically. LLM text is advisory and excluded from the grade. |
| C7 | The example's `structure` verdict ("no headers") is unspecified as a rule. | Structure uses Cppcheck findings and Lizard thresholds only. |
| C9 | The example describes a wall-clock smoke timeout, but wall-clock limits made grades vary under machine load, which violates the contract. | Limits judge CPU time, with a wall-clock backstop. See D8a in `DESIGN_DECISIONS.md`. |
| C8 | The brief's title differs slightly from the PDF's. | Cosmetic; the brief's title is used. |

## 5. Ambiguities and documented defaults

| Topic | Default chosen | Why |
|-------|----------------|-----|
| Test file format | `<id>.in` / `<id>.out`, optional `<id>.meta.json` | Assignment shows only `testset_dir` |
| Rule file schema | Assignment's shape, plus optional `execution`, `first_pass`, `scoring`, `report` | Backward compatible with the example |
| Path resolution | Relative to the rules file | Grades must not depend on the working directory |
| Smoke crash (not timeout) | Continue; set `smoke_crashed` | Assignment only defines the timeout case, and other tests may pass |
| Compilation failure | Execution metrics score 0, source metrics still run; `scoring.compile_failure_policy` can set `zero` | Matches the partial-report spirit; configurable |
| Tool missing | Metric is `not_evaluated`; excluded and the grade renormalised (`scoring.unavailable_policy`) | Never full marks, never a false zero |
| Skipped because of the submission | Metric is `blocked` and scores 0 | A hanging program must not score well on what remains |
| Weights not summing to 1 | Error by default; `scoring.weight_sum_policy: "normalize"` allows it | Catches typos |
| Metric `threshold` | Optional; reports pass/fail for that metric and does not alter the grade | Assignment says rules define a threshold but not its effect |

## 6. Dependencies

| Tool | Status | Purpose |
|------|--------|---------|
| Python ≥ 3.9 | Mandatory | Agent |
| C compiler (`gcc`/`clang`) | Mandatory | Compile submissions |
| Secure backend: `sandbox-exec` (macOS) or Docker | Mandatory unless `--allow-unsafe` | Isolation |
| `lizard`, `cppcheck` (pip) | Recommended | `structure` metric; reported as skipped if absent |
| `pytest` | Development | Test suite |
| ASan/UBSan | Optional | `memory_safety` metric |
| Ollama | Optional | Advisory readability text |

## 7. Implementation order

Skeleton → minimal grader (compile, run, compare, score, report) → analyzers → scoring and
feedback → isolation hardening → Ollama → QA → documentation.
