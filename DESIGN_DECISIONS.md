# Design Decisions

The assignment leaves the internals to the team ("yours to decide and defend"). Each entry
gives what was chosen, why, and what it costs.

## D1. Operation counts instead of a timing curve

**Choice.** Build with `-fsanitize-coverage=trace-pc`, count basic blocks, fit growth classes.
**Why.** The example uses timing, but timing changes with machine load, and the contract
requires the same grade every run. Counts are exact. A count measured at n=3200 for
`sort_bubble.c` is 10246407 on every run.
**Cost.** Time inside libc is invisible, so a `strlen` in a loop looks cheaper than it is
(demonstrated in `tests/test_limitations.py`). Builds use `-O0`, so the count reflects source
structure and not optimised speed.

## D2. Readability is scored deterministically; the LLM is advisory

**Choice.** The `llm_review` analyzer keeps the assignment's name, but its score comes from
fixed checks. Ollama remarks are attached, unscored.
**Why.** Even with temperature 0, a model's output can change with its version, so a scored
LLM cannot honour the contract. It also opens a route for a comment in student code to
influence marks.
**Cost.** Deterministic checks are shallower than a good reviewer. They can be gamed with long
meaningless names.

## D3. `blocked` and `not_evaluated` are different

**Choice.** A skip caused by the submission scores 0. A skip caused by the environment leaves
the denominator.
**Why.** With a single "skipped" status, either a hanging program would be graded only on its
style and could score full marks, or a missing Cppcheck would wrongly cost a student marks.
**Cost.** A little more logic in the scorer, and renormalised grades need the `partial` label
and the excluded list that come with them.

## D4. Refuse rather than downgrade

**Choice.** If no secure backend exists, grading stops with exit code 4. The unsafe backend
needs `--allow-unsafe`, and the report says so.
**Why.** A silent fallback would run untrusted code while appearing safe.
**Cost.** The agent will not run on a machine with neither Seatbelt nor Docker without an
explicit decision.

## D5. Seatbelt on macOS, even though it is deprecated

**Choice.** Use `sandbox-exec` as the primary macOS backend, with the interface open to Docker.
**Why.** Docker is not in the assignment, and it was not installed on the development machine.
Seatbelt ships with macOS, and the restrictions can be tested directly, which they are.
**Cost.** Apple may remove it, and it is weaker than a VM. See `SECURITY.md`.

## D6. Compile inside the sandbox too

**Why.** A compiler is not harmless on untrusted input: `#include "/Users/x/.ssh/id_rsa"`
would print the file's first line in an error, which would then land in a report. This was
reproduced, and the sandbox now blocks it.

## D7. Memory limit by polling

**Why.** `setrlimit(RLIMIT_AS)` raises `ValueError` on this macOS, and `RLIMIT_DATA` too, so
the usual approach does not work. The monitor reads `ri_phys_footprint` every 2 ms.
**Cost.** A process can overshoot briefly between polls. Under sanitizers no memory limit
applies, because ASan's shadow memory would distort it.

## D8. Retry a binary's first timeout

**Why.** Measured: macOS spends 170–580 ms on a new binary's first launch, compared with about
15 ms afterwards. Against a 1 s limit, this could fail a correct program once and pass it the
next time. A real hang times out twice, so its verdict does not change.
**Cost.** A hanging program costs one extra time limit.

## D8a. Time limits judge CPU time

**Choice.** A program is timed out when it has used `time_limit_s` of CPU time. A wall-clock
backstop of 5 times the limit catches programs that sleep forever. Compilers keep a plain
wall-clock limit, because their work happens in child processes this monitor cannot see.
**Why.** The assignment's example describes a wall-clock timeout, and the first version did that.
Under heavy load, `add_leak.c` graded 88.5 on most runs and 78.5 on one: the program was waiting
for a processor, not running, and that wait counted against it. CPU time barely changes with
load. After the change, all 18 samples matched their idle results in 3 rounds at three times the
machine's core count. This departs from the example's wording in order to keep the assignment's
contract, which it describes as the thing that must not change.
**Cost.** A sleeping program takes up to 5 times the limit to be stopped. CPU time still varies a
little, so a program using almost exactly its limit can flip.

## D9. Allocation tracker instead of LeakSanitizer

**Why.** LeakSanitizer reports "not supported on this platform" here, and `leaks --atExit`
reported no leaks on a program that leaked. Macro substitution (`-Dmalloc=ag_malloc`) works
under the sandbox and on every platform.
**Cost.** Memory allocated inside libc is not tracked, and memory still reachable at exit is
reported as "not freed at exit". The wording avoids calling it a proven leak.

## D10. Execution analyzers run serially

**Why.** Parallel runs compete for CPU, which could tip a borderline program over its limit.
The assignment says "in parallel where possible", and for execution this is not possible
without risking the contract. Source analyzers do run in parallel.
**Cost.** Grading takes a few seconds per submission rather than less.

## D11. A malformed test is excluded

**Choice.** It is listed in the report, and it counts neither as a pass nor against the student.
**Why.** Counting it as a pass would be false, and failing a student for an instructor's
mistake would be unfair. If every test is malformed, correctness is `not_evaluated`.

## D12. Nonzero exit fails a test by default

**Why.** C convention treats a nonzero exit as failure, so right output with exit status 3 is
not a correct program. `require_zero_exit: false` relaxes it.

## D13. Shingles, not single tokens

**Why.** Every C program shares `int`, `return`, and `{`. Sets of 5-token sequences compare
structure, so shared keywords carry little weight (tested). Identifiers become `ID`, which
makes renaming useless. Library names are kept because they carry meaning.
**Cost.** Very short programs have few shingles and collide easily (a documented false positive).

## D14. Flagged originality scores 0.5, not 0

**Why.** A flag is a request for review and not a finding. A zero would be a penalty for
something unproven. `flagged_score` is configurable.

## D15. Weights

The assignment's example gives correctness 20%. Under those rules `add_wrong.c`, which
multiplies instead of adding, still scores 71.95, because it does well on the other metrics.
The agent reports this faithfully. An instructor who disagrees can raise that weight in the
rules, with no code change, which is the point of external rules. Worth raising with the
professor.

## D16. Python 3.9 compatibility

macOS ships Python 3.9.6, and no Homebrew was present. Keeping to 3.9 means a new user has
nothing further to install.
