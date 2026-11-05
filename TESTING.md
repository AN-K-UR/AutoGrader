# Testing

## How to run

```bash
.venv/bin/python -m pytest
```

```bash
.venv/bin/python scripts/mutation_check.py
```

## Latest verified results

Run on Apple silicon macOS (Darwin 25.6), Python 3.9.6, Apple clang 21.0.0, Cppcheck 2.22.0,
Lizard 1.24.3, using the Seatbelt backend, from a fresh clone and a fresh virtual environment.

| Check | Result |
|-------|--------|
| pytest | 291 passed, 0 failed, 0 skipped, in about 3 minutes |
| Mutation check | 22 of 22 mutants killed |
| `verify-repro` | Same grade on repeated runs of `add_student`, `add_infinite_loop`, `add_memory_bug` (5 runs each) and `sort_bubble` (3 runs) |
| Sample run | All 18 samples graded; reports in `reports/samples/` |
| Grades under heavy load | All 18 samples matched their idle results in 3 rounds, with 30 busy processes on 10 cores |
| Web page in a real browser | `add_student.c` gave 81.02 and `add_infinite_loop.c` 42.50, matching the CLI; a program printing HTML and script tags ran nothing; no sideways scrolling at 375 px wide |

## What was not verified

Stated plainly, so nobody claims more than was done.

| Item | Status |
|------|--------|
| Docker backend | **Never run.** Docker was not installed. Only command construction and backend selection are tested, with mocks |
| Ollama | **Never run against a real server.** Ollama was not installed. Client behaviour is tested with a mocked HTTP layer |
| Linux | **Not tested.** Only the code paths that run on macOS have been exercised |
| GNU GCC | **Not tested.** `/usr/bin/gcc` here is Apple clang, so GCC's output format is covered only by parser unit tests |
| The professor's samples | **Not run.** `Example.tgz` contains no C submissions |

## Suite contents

| File | Tests | Covers |
|------|-------|--------|
| `test_config.py` | Rules | Valid and invalid files, weights, thresholds, typos, hashing |
| `test_process_runner.py` | Limits | Timeouts, killing children, output floods, memory, signals, no shell |
| `test_sandbox.py` | Isolation | Reads, writes, fork, shell, network, memory, compiler include, backend selection |
| `test_compiler.py` | Compilation | Success, syntax error, missing header, no compiler, timeout, parsing |
| `test_explain.py` | Explanations | Overflow, off by one, sign, layout, crash, limits |
| `test_analyzers_source.py` | Source analyzers | Lexer, modularity, readability, originality, static analysis, growth fitting |
| `test_analyzers_exec.py` | Execution analyzers | Correctness, comparison, edge cases, complexity, memory safety, syntax |
| `test_scoring.py` | Scoring | Hand-calculated grades, every status and policy, boundaries |
| `test_reports.py` | Reports | Fields, agreement between reports, size limits, missing sections |
| `test_llm.py` | Ollama client | Mocked server down, missing model, timeout, invalid reply |
| `test_end_to_end.py` | Whole agent | Every sample type, reproducibility, cleanup, bad paths, hostile names |
| `test_limitations.py` | Claimed limits | Each documented wrong verdict, actually demonstrated |
| `test_cli.py` | CLI | Commands, exit codes, refusal without a sandbox, unsafe labelling |
| `test_web.py` | Web interface | Same grade as the CLI, foreign requests, paths, size limits, no unsafe route |

## Mutation check

`scripts/mutation_check.py` makes one deliberate break at a time in critical code, such as
allowing `fork` in the sandbox or letting a blocked metric escape the denominator, and confirms
that the relevant tests fail. It restores each file afterwards. The first run caught 18 of 19.
The survivor showed that deduplication of repeated sanitizer findings had no test, and one was
added. This covers 22 selected mutations, so it is evidence about those points and not a measure
of full coverage.

## Safety of the tests

Fixtures are harmless. The sandbox probe only tries to open a file, create a file in a temporary
location, fork, run `/bin/echo`, and connect to a closed local port. Tests for hanging and
crashing programs run under limits. Nothing needs a network connection or a language model.

Sandbox tests are skipped automatically when `sandbox-exec` is absent, and pytest reports those
as skipped rather than passed. `test_memory_limit_stops_a_large_allocation` depends on the
monitor's timing, so it could be affected by an extremely loaded machine.

## Bugs found while testing

| Found by | Bug | Fix |
|----------|-----|-----|
| Reading the first report | `INT_MAX + 1` explained as "wrong sign" | Overflow check runs first |
| Reading the first report | One overflow at one line counted twice | Findings keyed by defect, not values |
| Reading the first report | First launch took 0.58 s against a 1 s limit | Retry on a first-run timeout |
| Sample run | A crash left complexity `not_evaluated`, excusing it from the grade | Now `blocked` |
| Review of the suite | A memory test accepted nearly any outcome | Now requires the kill |
| Mutation check | Deduplication was untested | Test added |
| Checking the docs | Demo weights summed to 1.20 | Script corrected |
| A test that failed once in a full run | Wall-clock limits let machine load change grades (88.5 versus 78.5), the most serious bug found | Limits judge CPU time; see D8a |
| Reading a sanitizer report | A memory address in the message could split one defect into several across runs | Addresses and values removed from the key |
