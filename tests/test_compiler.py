import unittest.mock as mock

from execution.compiler import compile_source, parse_diagnostics, split_flags
from execution.sandbox import UnsafeBackend
from models.results import ProcessResult, RunOutcome


def source(workdir, text):
    with open(f"{workdir}/s.c", "w", encoding="utf-8") as handle:
        handle.write(text)


def test_valid_program_compiles(backend, workdir):
    source(workdir, "int main(void) { return 0; }\n")
    result = compile_source(backend, "gcc", ["s.c"], "s.bin", ["-O2"], workdir, 20)
    assert result.success and result.binary == "s.bin"


def test_syntax_error_is_data_not_an_exception(backend, workdir):
    source(workdir, "int main(void) { return 0 }\n")
    result = compile_source(backend, "gcc", ["s.c"], "s.bin", [], workdir, 20)
    assert not result.success
    assert result.binary is None
    assert result.diagnostics[0].severity == "error"
    assert result.diagnostics[0].line == 1


def test_missing_header_is_reported(backend, workdir):
    source(workdir, "#include <no_such_header.h>\nint main(void) { return 0; }\n")
    result = compile_source(backend, "gcc", ["s.c"], "s.bin", [], workdir, 20)
    assert not result.success
    assert "no_such_header.h" in result.output


def test_compiler_unavailable(backend, workdir):
    source(workdir, "int main(void) { return 0; }\n")
    result = compile_source(backend, "no-such-compiler", ["s.c"], "s.bin", [], workdir, 20)
    assert not result.success
    assert "not found" in result.error


def test_compilation_timeout_is_structured(workdir):
    fake = UnsafeBackend()
    timed_out = ProcessResult(outcome=RunOutcome.TIMEOUT)
    with mock.patch.object(fake, "run_compiler", return_value=timed_out):
        result = compile_source(fake, "gcc", ["s.c"], "s.bin", [], workdir, 1)
    assert result.timed_out and not result.success


def test_warning_parsed_with_flag():
    text = "s.c:3:9: warning: unused variable 'x' [-Wunused-variable]\n"
    item = parse_diagnostics(text, "gcc")[0]
    assert (item.severity, item.line, item.code) == ("warning", 3, "-Wunused-variable")


def test_werror_keeps_the_underlying_warning_flag():
    text = "s.c:3:9: error: unused variable 'x' [-Werror,-Wunused-variable]\n"
    assert parse_diagnostics(text, "gcc")[0].code == "-Wunused-variable"
    text = "s.c:3:9: error: unused variable 'x' [-Werror=unused-variable]\n"
    assert parse_diagnostics(text, "gcc")[0].code == "-Wunused-variable"


def test_split_flags_accepts_both_forms():
    assert split_flags("-Wall -std=c11") == ["-Wall", "-std=c11"]
    assert split_flags(["-Wall"]) == ["-Wall"]
