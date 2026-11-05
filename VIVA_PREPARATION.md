# Viva Preparation

Answers describe the code as it exists. If you change the code, change this file.

## Project overview

AutoGrader is a command-line agent. Given a C file and an external JSON rules file, it compiles
and runs the program in a sandbox, evaluates each metric with a separate analyzer, combines the
scores with the rule weights, and writes a JSON report and a text report.

**Why rule-driven?** Instructors differ on what matters and each assignment has different needs.
Rules outside the code let an instructor change metrics, weights, and limits without
programming, and the rules hash records exactly what standard was applied.

## Data flow

Rules are loaded and validated, then a backend is chosen. The first pass compiles the program,
does a smoke run, and checks basic sanity. The coordinator dispatches the analyzers: source-only
ones in parallel and execution ones in series. The scorer computes the grade, feedback is built,
and both reports are written from one dictionary.

## Modules at a glance

| Module | Job |
|--------|-----|
| `coordinator` | Orders everything and decides what is skipped |
| `first_pass` | Compile, smoke run, static sanity |
| `config_loader` | Validates rules; reports every problem at once |
| `process_runner` | Runs one process under limits |
| `sandbox` | Backends: seatbelt, docker, unsafe |
| `correctness` | Instructor's tests |
| `edge_cases` | Generated corner cases against a reference solution |
| `syntax` | Compiler warnings |
| `static_analysis` | Cppcheck and Lizard |
| `modularity` | Function split |
| `complexity` | Growth from operation counts |
| `memory_safety` | ASan, UBSan, and the allocation tracker |
| `readability` | Deterministic style checks, optional LLM remarks |
| `originality` | Token-shingle similarity |
| `score_calculator` | The weighted formula |
| `feedback_generator` | Findings into actions |

## Scoring: worked example

Real output for `add_student.c` under `config/rules.json`. All nine metrics were scored, so the
denominator is 1.00.

| Metric | Weight | Score | Contribution (100 × w × s) |
|--------|--------|-------|---------------------------|
| correctness | 0.20 | 0.80 (8 of 10) | 16.00 |
| syntax | 0.10 | 1.00 | 10.00 |
| structure | 0.10 | 1.00 | 10.00 |
| modularity | 0.10 | 0.25 | 2.50 |
| logical | 0.10 | 0.8519 (23 of 27) | 8.52 |
| complexity | 0.10 | 1.00 | 10.00 |
| memory_safety | 0.10 | 0.75 | 7.50 |
| readability | 0.10 | 0.65 | 6.50 |
| originality | 0.10 | 1.00 | 10.00 |
| **Total** | 1.00 | | **81.02** |

**With a missing corpus:** originality becomes `not_evaluated`, so the denominator is 0.90 and
the grade is `100 × 0.7102 / 0.90 = 78.91`, marked `partial`. That is a lower grade, not a free
10 marks.

**With a hang:** the four execution metrics are `blocked`, so 0.5 of the weight scores 0 and stays
in the denominator. `add_infinite_loop.c` gets 42.50.

## Topics

**External configuration.** Weights in code would need a developer to change, and could not be
audited. The rules file is hashed into every report.

**Compilation versus runtime errors.** A compilation error means no program exists, so execution
metrics are blocked. A runtime error means the program ran and failed on some input, so it is
recorded per test and other tests still run.

**Test evaluation.** Each test is run, its output is compared under a named policy, and the exit
status is checked. Any forgiven difference is recorded. Timeouts, crashes, and limit violations
each have their own status.

**Static analysis** inspects code without running it, so it can reason about paths tests never
reach, but it produces false positives and warnings about things that never happen.

**Cyclomatic complexity** counts independent paths through a function. It is a measure of testing
effort and structure, unrelated to Big-O time complexity.

**Time complexity estimate.** The program is compiled with a counter called on every basic block,
run at several input sizes, and the counts are fitted to growth classes. The slowest-growing class
that fits within tolerance is chosen.

**Memory safety.** ASan catches invalid memory access at run time, UBSan catches undefined
behaviour such as signed overflow, and the allocation tracker reports memory not freed at exit.
All of them only see paths that ran.

**Similarity.** Tokens are normalized, 5-token shingles are collected, and Jaccard similarity is
computed against each corpus file.

**JSON design.** One versioned schema, status fields that distinguish zero from not evaluated,
hashes for reproducibility, and evidence attached to each score so that a mark can be traced.

**Error handling.** A submission's failure is data. Only rule errors, unusable paths, and a
missing sandbox stop the program, each with its own exit code.

**Trade-offs.** Determinism over depth for readability. Exact counts over real timing. Serial
execution over speed. Refusing to run over silently running unsafely.

**Future work.** Multi-file submissions, class-wide pairwise comparison, property-based inputs,
and verified Docker support.

---

## Viva questions

### Behaviour

**1. What happens if the source file does not compile?**
The compile error is stored, and execution metrics become `blocked` and score 0. `syntax` scores
0. Source-only metrics still run, and the report explains the error. `add_compile_error.c` gets
31.00. `compile_failure_policy: "zero"` gives 0 instead.

**2. What happens if one analyzer is unavailable?**
Its metric is `not_evaluated`, its weight leaves the denominator under the default policy, the
status becomes `partial`, and the reason is listed. If the analyzer itself raises an exception,
the same happens, and the rest of the evaluation continues.

**3. What happens if there are no test cases?**
`correctness` is `not_evaluated`. It is not 0, since the student did nothing wrong, and it is not
100, since nothing was shown.

**4. How are skipped checks treated during scoring?**
`blocked` scores 0 and stays in the denominator. `not_evaluated` is dropped, or scores 0 under
the `zero` policy. `disabled` is ignored. None of them earn marks.

**5. Can the agent give 100 to a wrong program?**
Yes. `add_passes_but_wrong.c` does exactly that, because no test reaches its bug. We show this
as a limitation.

**6. What if a test's expected-output file is missing?**
The test is malformed. It is listed in the report, not run, and neither passes nor fails. If
all tests are malformed, correctness is `not_evaluated`.

**7. What if the program prints the right answer but returns 3?**
The test fails by default, as a nonzero exit means failure in C. `add_exit_error.c` shows this.

**8. What if a program reads no input and prints nothing?**
Its output is compared like any other, and the failure says it printed nothing.

**9. What if a program prints forever?**
Output is capped at `max_output_bytes`. Past that the process is killed and the test gets the
status `output_limit`.

**10. What if the rules file has a typo?**
It is rejected with a message naming the setting and the valid options. All problems are
reported at once, with exit code 2.

**11. What if the weights do not sum to 1?**
This is an error by default, as it is usually a typo. `weight_sum_policy: "normalize"` allows it,
and the formula divides by the total anyway.

**12. If nothing can be evaluated, what is the grade?**
`null`, with status `not_gradable`. A 0 would wrongly imply the student was assessed and failed.

### Reasoning

**13. Can a high source-similarity score prove plagiarism?**
No. Two students can independently write nearly identical short programs, and our test shows a
false positive at 1.00. It is a reason for human review.

**14. Why is an LLM not the authority for correctness?**
It predicts plausible text rather than running the program, so it can be confidently wrong. Its
output may change between versions, which breaks reproducibility. Running real tests is a
measurement.

**15. Why is a timeout insufficient to secure untrusted execution?**
A timeout limits duration, not behaviour. A program can read secrets, delete files, or send data
in milliseconds. Isolation is what prevents those actions.

**16. How do we verify that the JSON and text reports agree on the final score?**
By construction: the text is rendered from the same dictionary written as JSON. A test also parses
the grade from the text and compares it.

**17. Why not use timing for complexity, as the example does?**
Timing changes with load, so the grade could differ between runs, which breaks the contract.
Operation counts are exact for a given program and input.

**18. Is the complexity estimate a proof?**
No. It is a fit to a few samples. It cannot see inside libc, and behaviour beyond the tested sizes
is unknown. A `strlen` in a loop shows as O(n) when it is really O(n²).

**19. Why compile with -O0 for counting?**
The optimiser can replace a loop with a formula, which would make a linear program look constant.

**20. Does "no sanitizer diagnostics" mean the program is memory-safe?**
No. Only that nothing was detected on the inputs we ran. The report says so, and
`add_hidden_memory_bug.c` shows a real bug being missed.

**21. How is reproducibility achieved?**
Operation counts, CPU-time limits, seeded generators, serial execution, paths relative to the rules file, an
advisory-only LLM, and a retry for macOS's first-launch delay. `verify-repro` checks the
fingerprint directly.

**22. Is it perfectly reproducible?**
Not across different compilers, which can change warnings or undefined behaviour. And a program
using almost exactly its CPU limit could flip. Load alone no longer changes grades: all 18 samples
matched in 3 rounds under heavy overload.

**23. Why does the Seatbelt backend retry a timeout?**
We measured macOS taking 170–580 ms on a new binary's first launch, against about 15 ms after.
Only the very first run of each binary is retried. A real hang times out both times.

**23a. Why CPU time and not wall-clock time?**
Under load, a program waits for a processor, and wall-clock time counts that against it. We saw
one submission grade both 88.5 and 78.5 for that reason. CPU time measures the work the program
did. A backstop of 5 times the limit still catches programs that sleep forever.

**24. Why are execution analyzers not run in parallel?**
Parallel runs compete for CPU, which could tip a borderline program over its limit, and then the
grade would depend on scheduling.

**25. Why does a crashing program still run the other tests?**
A crash on one input says nothing about others, and the assignment defines skipping only for a
timeout.

**26. Why does a hang skip tests, then?**
The assignment specifies that flow, and a program that hangs on the sample input would likely
hang on each test, wasting a time limit per test.

### Technical

**27. How is memory limited on macOS?**
`RLIMIT_AS` cannot be set there, so a monitor reads the physical footprint every 2 ms with
`proc_pid_rusage` and kills the process past the limit. A brief overshoot is possible.

**28. What does the Seatbelt profile do?**
It denies everything by default, then allows exec of that one binary, reads of system libraries
and the work directory, and writing to `/dev/null`. Fork, sockets, and other writes are denied.

**29. Why sandbox the compiler?**
`#include "/path/to/secret"` would make the compiler print part of that file in an error. We
reproduced that, and then blocked it.

**30. What is Jaccard similarity?**
The size of the intersection divided by the size of the union of two sets. Identical sets give 1,
and disjoint sets give 0.

**31. Why normalize identifiers?**
So that renaming variables does not change the fingerprint. `add_copied.c` has every name
changed and still scores 1.00.

**32. How are comments handled in similarity?**
They are removed, so adding or rewriting them has no effect.

**33. Why doesn't the shared use of `int` and `return` inflate similarity?**
We compare 5-token sequences rather than single tokens, so common keywords alone do not match.

**34. How are counter test cases generated?**
A seeded generator produces inputs per category, such as overflow or empty arrays, and the
instructor's reference solution provides expected output. Any disagreement is a counterexample,
sorted shortest first.

**35. Without a reference solution, what can it detect?**
Only crashes, hangs, and limit violations, because nothing says what the right answer is. The
report states this.

**36. How is a new metric added?**
With an existing analyzer, one entry in the rules file. For a new kind of check, a new module in
`analyzers/` that uses `@register`, which is discovered automatically.

**37. Why use subprocess without a shell?**
With a list of arguments, nothing is interpreted, so a filename containing `$(...)` is just text.
The source is also copied to a fixed name.

**38. Why the difference between blocked and not_evaluated?**
Responsibility. A student who causes a skip should not benefit, and a student should not lose
marks because of a missing tool.

**39. What does the threshold in a metric do?**
It reports whether the metric was met (`met_threshold`). It does not change the grade, which
comes from the weights alone. The assignment does not define its effect, so this is our choice.

**40. How do you know the tests are meaningful?**
`scripts/mutation_check.py` breaks critical logic on purpose, for example allowing `fork` or
removing the timeout, and confirms a test fails. It found one gap, which we then closed.

**45. Does the web page use a different grader?**
No. It calls the same `evaluate` function as the CLI, and a test confirms the fingerprints match.
It is an interface only, and the assignment does not require it.

**46. What stops a student's output from attacking the page?**
All report text is inserted with `textContent`, so it is never parsed as HTML. A strict
Content-Security-Policy would also block inline scripts. We tested a program printing script tags.

**47. Could a website I visit use the local server?**
It is rejected. The server checks `Host` and `Origin`, and it only accepts `application/json`,
which a cross-site form cannot send without a preflight that we never answer.

**48. Where is Ollama used?**
Only in the readability metric, through `analyzers/llm_client.py`, called from
`_advisory` in `analyzers/readability.py`. It adds unscored remarks, and it is off unless
`use_llm` is true and Ollama is running. Everything else works without it.

### About the assignment

**41. Your grade for the example is 81.02, but the assignment says 89. Why?**
The assignment's numbers add up to 79, not 89, and they are illustrative. `tests/test_scoring.py`
checks that sum. Our 81.02 comes from real runs with our own tests and thresholds, so the
individual metrics differ too.

**42. The example shows `-Wunused-parameter`. Do you?**
No. `add.c` declares `main()` with no parameters, so that warning cannot occur. We report what
the compiler emits.

**43. What are the most important limitations?**
Tests and sanitizers only see what runs, complexity cannot see inside libc, and similarity has both
false positives and false negatives. Each is demonstrated in `tests/test_limitations.py`.

**44. Did you use AI tools?**
Answer truthfully. The code was generated with Claude Code. The assignment allows this as long
as you own the work, so be ready to explain and change your part.
