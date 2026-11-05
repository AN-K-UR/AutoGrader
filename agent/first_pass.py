"""The coordinator's cheap sanity sweep: compile, smoke run, static sanity."""
from __future__ import annotations

from typing import Dict, Optional

from agent.config_loader import Rules
from analyzers.c_source import CSource
from analyzers.explain import explain_process_failure
from analyzers.testset import load_testset
from execution.compiler import compile_source, split_flags
from execution.process_runner import Limits
from execution.sandbox import ExecutionBackend
from models.results import CompileResult, FirstPass, RunOutcome

_READERS = frozenset({"scanf", "fscanf", "sscanf", "getchar", "gets", "fgets", "getline",
                      "fread", "read", "getc"})
_WRITERS = frozenset({"printf", "puts", "putchar", "fprintf", "fputs", "fwrite", "write",
                      "putc"})


def static_sanity(source: CSource) -> Dict[str, bool]:
    """Token-based, so ``// printf`` does not count as a call."""
    main = source.function("main")
    called = source.called_names()
    has_return = bool(main) and any(token.text == "return"
                                    for token in source.tokens_in_function(main))
    return {
        "has_main": main is not None,
        "calls_reader": bool(called & _READERS),
        "calls_writer": bool(called & _WRITERS),
        "main_returns": has_return,
    }


def _smoke_input(rules: Rules) -> Optional[str]:
    configured = rules.first_pass["smoke_input"]
    if configured is not None:
        return str(configured)
    directory = rules.first_testset()
    if directory is None:
        return None
    try:
        for case in load_testset(directory):
            if not case.error:
                return case.input
    except FileNotFoundError:
        pass
    return None


def run_first_pass(rules: Rules, backend: ExecutionBackend, workdir: str, source_file: str,
                   source: CSource) -> "tuple[FirstPass, CompileResult]":
    """Run the sweep. Only ``binary`` on the compile result decides what runs next."""
    execution = rules.execution
    result = FirstPass(static_sanity=static_sanity(source))
    compiled = compile_source(backend, execution["compiler"], [source_file], "submission.bin",
                              split_flags(rules.first_pass["compile_flags"]), workdir,
                              execution["compile_timeout_s"], execution["link_flags"])
    result.compiled = compiled.success
    if not compiled.success:
        result.smoke_detail = "not run: compilation failed"
        return result, compiled

    text = _smoke_input(rules)
    limits = Limits(time_s=rules.time_limit_s, memory_mb=rules.memory_limit_mb,
                    output_bytes=execution["max_output_bytes"],
                    max_processes=execution["max_processes"])
    process = backend.run_binary(compiled.binary, limits, (text or "").encode("utf-8"), workdir)
    result.smoke_ran = True
    if process.outcome == RunOutcome.TIMEOUT:
        result.suspected_infinite_loop = True
        result.smoke_detail = explain_process_failure(process, limits)
    elif process.outcome != RunOutcome.EXITED or process.exit_code != 0:
        result.smoke_crashed = True
        result.smoke_detail = explain_process_failure(process, limits)
    else:
        result.smoke_ok = True
        result.smoke_detail = f"exited cleanly in {process.duration_s:.3f} s"
    return result, compiled
