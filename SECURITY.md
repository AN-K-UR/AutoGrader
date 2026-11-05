# Security

Submitted programs are untrusted. This document states what is actually enforced, what has
been tested, and what remains unprotected. **AutoGrader has not had an independent security
review and is not claimed to be production-secure.**

## Threats considered

| Threat | Example | Defence |
|--------|---------|---------|
| Runaway time | `while (1);` | CPU-time kill of the process group, wall-clock backstop, `RLIMIT_CPU` |
| Runaway memory | Allocating gigabytes | Footprint monitor (macOS), `--memory` (Docker) |
| Output flood | `for (;;) puts("x");` | Capped readers, then kill |
| Fork bomb | `while (1) fork();` | Fork denied by the profile; `--pids-limit` (Docker) |
| Reading secrets | Opening `~/.ssh/id_rsa` | File reads denied outside system paths |
| Leaking via compiler | `#include "/Users/x/.ssh/id_rsa"` | The compiler is sandboxed as well |
| Damaging files | Deleting the home directory | All writes denied |
| Data exfiltration | Opening a socket | Network denied |
| Running other programs | `system("...")` | Exec denied |
| Shell injection | A file named `$(rm -rf ~).c` | No shell is used; the source is copied to a fixed name |
| Report poisoning | Huge or binary output | Output capped, invalid bytes replaced |
| Prompting the LLM | A comment saying "award full marks" | The LLM cannot affect the grade |

## Backends

### `seatbelt` (macOS, default here)

The profile starts from `(deny default)`. Each row below is verified by `tests/test_sandbox.py`
with a harmless probe program.

| Attempt | Result |
|---------|--------|
| Read a file outside system paths | Blocked |
| Write in any location, including its work directory | Blocked |
| `fork()` | Blocked |
| `system()` | Blocked |
| TCP connect, even to localhost | Blocked |
| Compiler `#include` of a host file | Blocked |
| Allocate past the memory limit | Killed |

**Remaining exposure**

- `sandbox-exec` is deprecated by Apple and could change or disappear.
- It shares the host kernel, so a kernel exploit is out of scope.
- `file-read-metadata` is allowed, so a program can test whether a path exists and read its
  size and dates, though not its contents.
- System libraries are readable, as is the program's own work directory.
- `sysctl-read` is allowed, so a program can learn hardware details.
- CPU is not capped beyond the time limit.
- Memory is polled, so a brief overshoot is possible before the kill.
- Environment variables are reduced to a minimal set, but the shims' stderr markers are not
  authenticated: a program could print a false marker and then exit with `_exit`, which skips
  the real one. This could mislead the complexity or leak checks for that submission.

### `docker`

Containers run with no network, a read-only root, all capabilities dropped,
`no-new-privileges`, a non-root user, and memory, CPU, and process limits. The work directory
is mounted read-only for runs.

**Docker was not installed during development, so this backend has not been run.** Only its
command construction is tested. Verify it on your machine before relying on it. Containers
also share a kernel, so they are not a complete boundary either. On macOS, Docker Desktop must
be able to share the temporary directory that the agent uses.

### `unsafe`

No isolation. The program runs with your full privileges, with only time, memory, and output
limits. It is never selected automatically. It requires `--allow-unsafe`, and it logs a
warning and labels the report. Use it only for code you trust.

## Web interface

| Protection | Purpose |
|------------|---------|
| Binds to `127.0.0.1` only | Other machines cannot reach it |
| `Host` header check | Defeats DNS rebinding |
| `Origin` and content-type checks | Stops other websites posting through your browser |
| No unsafe option | Grading always needs a secure backend |
| Rule sets chosen from a fixed list | A request cannot name a path |
| Allow-list of static files | Project files cannot be fetched |
| `textContent` only, plus a strict Content-Security-Policy | Program output cannot run as a script |
| 1 MB source limit | Bounds the work one request causes |

Each row has a test in `tests/test_web.py`. In a real browser, a program printing `<img onerror>`
and `<script>` tags was shown as plain text and nothing ran. There is no login or rate limit, and
anyone with access to your user account can use it. It is a tool for one person on one computer.
**Do not put it on a network or behind a public tunnel.**

## Why a timeout is not enough

A timeout limits how long a program runs, not what it does. A program needs only milliseconds
to read a key file, delete a directory, or send data over the network. Isolation has to stop
those actions, and limits are a separate concern.

## What the agent does with your data

- Reports contain the file name, hashes, and tool versions, but not absolute host paths or
  environment variables.
- Student code is sent nowhere. The optional LLM accepts only a loopback address.
- Temporary directories are removed after each evaluation, unless `--keep-temp` is given.

## Recommendations for real use

Grade inside a disposable virtual machine or a dedicated account with no credentials on it.
Do not grade on a machine holding sensitive data. Run the Docker backend only after testing it
yourself. Rate-limit and authenticate any web front end, which this project does not include.
