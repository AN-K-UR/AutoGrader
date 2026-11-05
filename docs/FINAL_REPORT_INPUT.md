# Usefulness and Limitations

Input for the final report's required section. Each limitation names a concrete wrong or
unreliable verdict, and each is demonstrated by `tests/test_limitations.py`, except where
noted. The same material appears in every generated report, from
`config/usefulness_limitations.json`.

## Usefulness

1. **First-pass grading of large classes.** A lab of 300 students submits `add.c`. The agent
   grades each one under the same rules with no one watching, and a hung submission costs only
   its time limit. Benefit: consistent, repeatable marks, with staff time moved to the unusual
   cases.
2. **Instant formative feedback.** A student whose program prints `-2147483648` for
   `2147483647 1` sees that input, the expected `2147483648`, and a note that a gap of 2^32 is
   the signature of 32-bit overflow. Benefit: learning from a specific case rather than a bare
   mark.
3. **Plagiarism and LLM-copy triage.** `add_copied.c`, a peer's program with every name
   changed, scores similarity 1.00 against a 0.85 threshold and is flagged. Benefit: manual
   review is narrowed to suspicious pairs, and a person still decides.
4. **Coding-interview screens.** On a sorting task, `sort_correct.c` measures O(n log n) and
   `sort_bubble.c` measures O(n^2), though both pass every test. Benefit: filtering in which
   each decision can be explained metric by metric.

## Limitations

1. **Tests cannot prove correctness.** `add_passes_but_wrong.c` returns 0 for the input
   `31337 271828` only. No test or generated case tries it, so the agent gives **100/100 to a
   wrong program**. Mitigation: a larger random budget and property-based inputs. A pass is
   evidence, not proof.
2. **Sanitizers only see executed paths.** `add_hidden_memory_bug.c` overflows a heap block
   only when the first number is 31337. `memory_safety` reports no diagnostics and full marks,
   and the bug remains. Mitigation: widen the inputs, and never present a clean run as proof.
3. **Complexity estimates cannot see inside libc.** A loop with `strlen(text)` in its condition
   is really O(n^2), but the agent reports **O(n)**, because libc is not instrumented.
   Mitigation: treat this as an estimate, and combine it with timing or a check for library
   calls inside loops.
4. **False positives on trivial problems.** Two independently written minimal `add.c` programs
   normalise to the same tokens, so the agent reports similarity 1.00 and raises a flag although
   neither copied. Mitigation: the report marks short programs as low confidence, and a flag
   asks only for human review.
5. **False negatives on rewrites and unseen sources.** An LLM-written solution absent from the
   corpus, or a copy restructured into different functions, is not flagged. The agent cannot
   search the internet or recognise LLM authorship. Mitigation: seed the corpus with solutions
   from common LLMs and tutorials, and confirm ownership in a viva.

A further case, not automated because it depends on timing: a program that uses almost exactly
its CPU time limit can pass on one run and time out on another, which is the one place the
reproducibility contract can bend for a valid program. Heavy machine load alone did not change
any sample's grade once limits measured CPU time.
