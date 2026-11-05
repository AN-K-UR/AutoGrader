# Project Demonstration

A script for the lab evaluation and the 15–20 minute video. Every command is real. The results
quoted were produced on an Apple silicon Mac with Apple clang 21. Grades can differ on another
toolchain, so run the demo yourself first and use your own output.

## Prepare (before recording)

```bash
scripts/setup.sh
```

```bash
.venv/bin/python -m pytest -q
```

## Using the web page instead

Every part below can also be shown in the browser, which is easier to follow on video:

```bash
.venv/bin/python main.py serve
```

Open <http://127.0.0.1:8000>, choose a sample from the menu, and press **Grade submission**. The
grades match the commands below.

## Part 1: The problem (2 min)

Explain that manual marking is slow and inconsistent. State the contract: same submission +
same rules → same grade. Show [config/rules.json](config/rules.json), and point out that the
metrics, weights, and limits all live outside the code.

```bash
.venv/bin/python main.py check-tools
```

```bash
.venv/bin/python main.py validate-config --config config/rules.json
```

## Part 2: The assignment's example (4 min)

```bash
.venv/bin/python main.py grade --source submissions/examples/add_student.c --config config/rules.json --output reports/ --print-report
```

**Expected:** grade **81.02**. Tests 07 and 08 fail on overflow. Show `INPUT`, `EXPECTED`,
`GOT`, and `WHY`. Mention that the assignment's example states 89 although its own numbers sum
to 79, and that the agent's numbers come from real runs.

## Part 3: Things going wrong (4 min)

```bash
.venv/bin/python main.py grade --source submissions/examples/add_infinite_loop.c --output reports/
```

**Expected:** 42.50, `partial`, flag `suspected_infinite_loop`. Execution metrics are blocked at
0, and source metrics still run. This is the assignment's described flow.

```bash
.venv/bin/python main.py grade --source submissions/examples/add_compile_error.c --output reports/
```

**Expected:** 31.00, with the compile error explained in the report.

```bash
.venv/bin/python main.py grade --source submissions/examples/add_crash.c --output reports/
```

**Expected:** 46.75, with the crash named by signal in the failing tests.

## Part 4: What tests alone miss (3 min)

```bash
.venv/bin/python main.py grade --source submissions/examples/add_memory_bug.c --output reports/
```

**Expected:** 78.50. Every test passes, but `heap-buffer-overflow` and the leak are both found.

```bash
.venv/bin/python main.py grade --source submissions/examples/sort_bubble.c --config config/rules_sort.json --output reports/ --print-report
```

**Expected:** 90.00. All tests pass, but the estimate is O(n^2) against a required O(n log n).
Compare with `sort_correct.c`, which measures O(n log n).

## Part 5: Copying (2 min)

```bash
.venv/bin/python main.py grade --source submissions/examples/add_copied.c --output reports/ --print-report
```

**Expected:** 95.00, flag `suspected_copying` at similarity 1.00 against `peers/peer_a.c`,
although every name differs. Stress that this is a request for review, not proof.

## Part 6: Changing the rules without changing the code (2 min)

Live, edit `config/rules.json`: give `correctness` a weight of 0.60 and each of the other eight
metrics 0.05, so they still sum to 1.00. Re-run `add_student.c` and show the grade change with no
code edit. Then try a total other than 1.00, to show the agent reject it with a clear message, and
restore the file.

Next, show `banned_calls` in [config/rules_sort.json](config/rules_sort.json), a metric added
through the rules alone.

## Part 7: Reproducibility (1 min)

```bash
.venv/bin/python main.py verify-repro --source submissions/examples/add_student.c --runs 5
```

**Expected:** `REPRODUCIBLE: 5 runs produced the same grade`.

## Part 8: Safety (1 min)

```bash
.venv/bin/python -m pytest tests/test_sandbox.py -v
```

Each test name is a statement about what a submission cannot do. Then explain that the sandbox
is defence in depth, with the known gaps in [SECURITY.md](SECURITY.md).

## Part 9: Limitations (2 min)

```bash
.venv/bin/python main.py grade --source submissions/examples/add_passes_but_wrong.c --output reports/
```

**Expected:** 100.00 for a program that is wrong on one input. This is the honest ending: show
that it can be wrong, then present the rest of the
[limitations](docs/FINAL_REPORT_INPUT.md).

## Before the evaluation

- Do not rely on Wi-Fi: nothing here needs a network.
- Do not claim the Docker backend or Ollama was verified live unless you have since done so.
- Keep [reports/samples/SUMMARY.md](reports/samples/SUMMARY.md) open as a fallback.
