# Architecture

## Layers

Imports only point downward, so there are no cycles.

| Layer | Package | Responsibility | May import |
|-------|---------|----------------|------------|
| Interface | `main.py`, `web/` | Arguments and exit codes; local web page | everything below |
| Coordination | `agent/` | Load rules, first pass, dispatch, collate | analyzers, execution, scoring |
| Output | `reporting/` | Turn an evaluation into files | models |
| Decision | `scoring/` | Grade and feedback from results | models |
| Evaluation | `analyzers/` | One metric each | execution, models |
| Execution | `execution/` | Run compilers and binaries under limits | models |
| Data | `models/` | Plain result dataclasses | nothing |

`scoring/` never imports an analyzer, and `reporting/` never computes a score. That is what
lets each be tested with hand-built data.

## Data flow for one submission

1. `main.py` calls `load_rules`, which validates everything and hashes the file.
2. `coordinator.evaluate` picks a backend, refusing if none is secure.
3. A private temporary directory is created, and the source is copied in as `submission.c`.
   The original name is never given to the compiler.
4. `run_first_pass` compiles, does a smoke run, and checks static sanity.
5. `dispatch` runs each enabled analyzer once and returns `MetricResult`s in rule order.
6. The workspace is removed, even if an error occurred.
7. `calculate_score` fills in contributions and produces the summary.
8. `build_feedback` assembles failures, ranked suggestions, and skipped checks.
9. `build_report` makes one dictionary, from which both report files are written.

## The analyzer contract

```python
class Analyzer:
    name = "..."             # what the rules file refers to
    needs_execution = False  # True means skipped when the program cannot run
    PARAMS = {...}           # validated before anything runs

    def run(self, context, params) -> AnalyzerResult: ...
```

`AnalyzerResult` always carries a status, a score or `None`, feedback, and evidence, plus
optional suggestions, counterexamples, flags, and skipped tools. A submission's bug is a
result, never an exception. If an analyzer does raise, the coordinator records that metric as
`not_evaluated` with the reason, and the evaluation continues.

## Coordination

| Decision | Behaviour |
|----------|-----------|
| Compilation failed | Execution analyzers are `blocked`; source analyzers run |
| Smoke run timed out | `suspected_infinite_loop` flag; same as above; partial report |
| Smoke run crashed | `smoke_crashed` flag; analyzers still run, since other inputs may work |
| Source-only analyzers | Run in a thread pool of up to 4 |
| Execution analyzers | Run one at a time |

Execution analyzers are serial on purpose. Concurrent load could push a borderline program
past its limit, which would make the grade depend on scheduling.

## Execution

`ExecutionBackend` has two operations, `run_compiler` and `run_binary`, so everything above it
is backend-agnostic. All backends return a `ProcessResult` built by `run_process`.

| Limit | Enforcement on macOS |
|-------|---------------------|
| CPU time | Monitor reads the program's CPU time and kills the process group at the limit |
| Wall time | Backstop at 5 times the limit, for programs that sleep |
| CPU time, in the kernel | `RLIMIT_CPU`, as a second backstop |
| Memory | Monitor polls `proc_pid_rusage` physical footprint, every 2 ms |
| Output | Capped readers; the process is killed past the cap |
| Fork, exec, network, writes | Seatbelt profile |

## Extra builds

| Build | Flags | Used by |
|-------|-------|---------|
| `submission.bin` | `-O2 -Wall -Wextra -std=c11` | First pass, tests, edge cases |
| `counted.bin` | `-O0 -fsanitize-coverage=trace-pc` + `op_counter.c` | Complexity |
| `sanitized.bin` | `-fsanitize=address,undefined -g -O1` | Memory safety |
| `tracked.bin` | `-Dmalloc=ag_malloc ...` + `leak_shim.c` | Leak check |
| `reference.bin` | First-pass flags | Edge-case oracle |

The shims report through a marker on stderr, because the sandboxed program has nowhere it can
write a file.

## Web interface

`web/server.py` is a thin standard-library HTTP layer over `evaluate`, `build_report`, and
`render_text`. It writes the posted source to a temporary directory and grades it through the
same path as the CLI, so a test can compare fingerprints between them. A lock keeps gradings from
overlapping, because concurrent execution could affect a borderline time limit. The page in
`web/static/` is plain JavaScript with no external files, so a demo needs no internet.

## Reproducibility

| Source of variation | Treatment |
|---------------------|-----------|
| Machine load | Operation counts instead of timing; limits judge CPU time; execution serial |
| Random inputs | Seeded generators; the seed is a rule |
| LLM output | Advisory only; excluded from grade and fingerprint |
| Working directory | Paths resolve against the rules file |
| macOS first-launch delay | One retry when a binary's first run times out |
| Tests changing | Test set hashed into the report and the fingerprint |

`grade_fingerprint` hashes the source, rules, tests, grade, status, and each metric's score.
Two runs agree if and only if their fingerprints match, which `verify-repro` checks.
