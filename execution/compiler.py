"""Compiles C sources through an execution backend and parses diagnostics."""
from __future__ import annotations

import re
import shlex
from typing import List, Optional, Sequence

from execution.sandbox import ExecutionBackend
from models.results import CompileResult, Diagnostic, RunOutcome

_DIAGNOSTIC = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+):\s+"
    r"(?P<severity>warning|error|fatal error):\s+(?P<message>.*?)"
    r"(?:\s+\[(?P<code>-W[^\]]+|-Werror[^\]]*)\])?$",
    re.MULTILINE,
)


def split_flags(flags: object) -> List[str]:
    """Accept flags as the rule file's string or as a list."""
    if isinstance(flags, str):
        return shlex.split(flags)
    return [str(flag) for flag in flags]  # type: ignore[union-attr]


def parse_diagnostics(output: str, tool: str) -> List[Diagnostic]:
    """Parse ``file:line:col: severity: message [-Wflag]`` lines."""
    found = []
    for match in _DIAGNOSTIC.finditer(output):
        code = match.group("code")
        if code and code.startswith("-Werror,"):
            code = code.split(",", 1)[1]
        elif code and code.startswith("-Werror="):
            code = "-W" + code.split("=", 1)[1]
        found.append(Diagnostic(
            tool=tool,
            severity="error" if "error" in match.group("severity") else "warning",
            message=match.group("message"),
            line=int(match.group("line")),
            column=int(match.group("col")),
            code=code,
        ))
    return found


def compile_source(
    backend: ExecutionBackend,
    compiler: str,
    sources: Sequence[str],
    output: Optional[str],
    flags: Sequence[str],
    workdir: str,
    timeout_s: float,
    link_flags: Sequence[str] = (),
) -> CompileResult:
    """Compile ``sources`` (paths relative to ``workdir``).

    With ``output`` set to None the compiler only checks syntax. Failure is
    returned as data, never raised, so a broken submission still gets a report.
    """
    args = list(flags) + list(sources)
    args += ["-o", output] + list(link_flags) if output else ["-fsyntax-only"]
    process = backend.run_compiler(compiler, args, workdir, timeout_s)
    text = "\n".join(part for part in (process.stdout, process.stderr) if part)

    if process.outcome == RunOutcome.FAILED_TO_START:
        return CompileResult(False, compiler, list(flags), error=process.error)
    if process.outcome == RunOutcome.TIMEOUT:
        return CompileResult(False, compiler, list(flags), output=text, timed_out=True,
                             error=f"compilation exceeded {timeout_s:g} s")
    success = process.clean_exit
    return CompileResult(
        success=success,
        compiler=compiler,
        flags=list(flags),
        exit_code=process.exit_code,
        output=text,
        diagnostics=parse_diagnostics(text, compiler),
        binary=output if success else None,
        error="" if success else f"compiler exited with status {process.exit_code}",
    )
