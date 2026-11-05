"""Limits at the process layer, using small system tools and harmless scripts."""
import os
import sys
import time

from execution.process_runner import Limits, describe_signal, run_process
from models.results import RunOutcome

ENV = {"PATH": "/usr/bin:/bin"}
PY = sys.executable


def run(code, stdin=b"", **limits):
    settings = dict(time_s=5, memory_mb=None)
    settings.update(limits)
    return run_process([PY, "-S", "-c", code], Limits(**settings), stdin, env=dict(os.environ))


def test_captures_stdout_stderr_and_exit_code():
    result = run("import sys;print('out');print('err',file=sys.stderr);sys.exit(3)")
    assert result.outcome == RunOutcome.EXITED
    assert (result.stdout, result.stderr, result.exit_code) == ("out\n", "err\n", 3)
    assert not result.clean_exit


def test_stdin_is_delivered():
    assert run("print(input())", b"hello\n").stdout == "hello\n"


def test_empty_output_is_a_clean_exit():
    result = run("pass")
    assert result.clean_exit and result.stdout == ""


def test_infinite_loop_is_killed_near_the_limit():
    started = time.monotonic()
    result = run("while True: pass", time_s=0.3)
    assert result.outcome == RunOutcome.TIMEOUT
    assert result.exit_code is None
    assert time.monotonic() - started < 3


def test_waiting_does_not_count_against_the_limit():
    # A process that is not using the CPU has not spent its time limit. This is the
    # property that stops a busy machine from failing a correct program.
    assert run("import time;time.sleep(0.6)", time_s=0.3).clean_exit


def test_cpu_time_is_measured_in_real_seconds():
    # Mach ticks are not nanoseconds on Apple silicon, so a wrong conversion would
    # fire this limit far too early or far too late.
    started = time.monotonic()
    result = run("while True: pass", time_s=0.5)
    assert result.outcome == RunOutcome.TIMEOUT
    assert 0.4 < time.monotonic() - started < 2.0


def test_tools_can_ask_for_a_plain_wall_clock_limit():
    result = run("import time;time.sleep(30)", time_s=0.3, cpu_based=False)
    assert result.outcome == RunOutcome.TIMEOUT
    assert result.duration_s < 1.0


def test_sleeping_process_is_timed_out_too():
    assert run("import time;time.sleep(30)", time_s=0.3).outcome == RunOutcome.TIMEOUT


def test_timeout_kills_child_processes():
    code = ("import subprocess,time,sys;"
            "p=subprocess.Popen(['/bin/sleep','30']);print(p.pid,flush=True);time.sleep(30)")
    result = run(code, time_s=1.0)
    assert result.outcome == RunOutcome.TIMEOUT
    pid = int(result.stdout.strip())
    time.sleep(0.2)
    try:
        os.kill(pid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    assert not alive


def test_excessive_output_is_capped_and_stopped():
    result = run("while True: print('x'*1000)", output_bytes=10_000)
    assert result.outcome == RunOutcome.OUTPUT_LIMIT
    assert result.stdout_truncated
    assert len(result.stdout) <= 10_000


def test_excessive_stderr_is_capped():
    code = "import sys\nwhile True: sys.stderr.write('e'*1000)"
    assert run(code, output_bytes=10_000).outcome == RunOutcome.OUTPUT_LIMIT


def test_memory_limit_stops_a_large_allocation():
    # Touching every page makes the allocation real rather than merely reserved.
    code = "b=bytearray(300*1024*1024)\nb[::4096]=b'x'*len(b[::4096])\nimport time;time.sleep(2)"
    assert run(code, memory_mb=64).outcome == RunOutcome.MEMORY_LIMIT


def test_signal_is_reported():
    result = run("import os,signal;os.kill(os.getpid(),signal.SIGSEGV)")
    assert result.outcome == RunOutcome.SIGNALED
    assert describe_signal(result.signal) == "SIGSEGV"


def test_missing_program_is_not_an_exception():
    result = run_process(["/nonexistent/program"], Limits(time_s=1), env=ENV)
    assert result.outcome == RunOutcome.FAILED_TO_START


def test_no_shell_interpretation_of_arguments():
    result = run_process(["/bin/echo", "$(whoami); ls"], Limits(time_s=2), env=ENV)
    assert result.stdout == "$(whoami); ls\n"


def test_undecodable_output_is_tolerated():
    result = run("import sys;sys.stdout.buffer.write(bytes([255,254]))")
    assert result.clean_exit
