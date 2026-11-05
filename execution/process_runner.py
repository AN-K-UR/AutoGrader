"""Runs one child process under time, memory, and output limits.

Every backend funnels through :func:`run_process`, so all of them report results
the same way. No shell is ever involved: ``argv`` is passed straight to exec.

macOS note: ``RLIMIT_AS`` and ``RLIMIT_DATA`` cannot be lowered there (setrlimit
raises ValueError, tested on Darwin 25), so memory is enforced by polling the
child's physical footprint with ``proc_pid_rusage`` and killing it past the
limit. Polling can overshoot by a few milliseconds of allocation.

Time limits judge CPU time, not elapsed time. On a busy machine a program spends
time waiting for a processor, and counting that made a correct program time out
at random (seen under load: one submission graded both 88.5 and 78.5). A wall-clock
backstop still catches programs that sleep forever and use no CPU.
"""
from __future__ import annotations

import ctypes
import math
import os
import resource
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import IO, Callable, Dict, List, Optional, Sequence, Tuple

from models.results import ProcessResult, RunOutcome

POLL_INTERVAL_S = 0.002
_KILL_REAP_TIMEOUT_S = 5.0
WALL_BACKSTOP_FACTOR = 5.0
# Size of the buffer handed to proc_pid_rusage; rusage_info_v0 needs far less.
_RUSAGE_BUFFER_BYTES = 512
# Byte offsets in rusage_info_v0: a 16-byte uuid, then uint64 fields.
_USER_TIME_OFFSET = 16
_SYSTEM_TIME_OFFSET = 16 + 8
_FOOTPRINT_OFFSET = 16 + 7 * 8

# pid -> (CPU seconds, memory bytes), or None if the process cannot be read.
Sampler = Callable[[int], Optional[Tuple[float, int]]]


@dataclass
class Limits:
    """Resource limits for one run. ``None`` disables that limit."""

    time_s: float
    memory_mb: Optional[int] = None
    output_bytes: int = 1_000_000
    max_processes: int = 16
    max_open_files: int = 64
    # False for tools that work through child processes, such as a compiler,
    # whose CPU time this monitor cannot see.
    cpu_based: bool = True


class _MachTimebase(ctypes.Structure):
    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]


def _darwin_sampler() -> Optional[Sampler]:
    try:
        lib = ctypes.CDLL("/usr/lib/libproc.dylib")
        system = ctypes.CDLL("/usr/lib/libSystem.dylib")
    except OSError:
        return None
    timebase = _MachTimebase()
    system.mach_timebase_info(ctypes.byref(timebase))
    # CPU times arrive in Mach ticks, which are not nanoseconds on Apple silicon.
    seconds_per_tick = timebase.numer / timebase.denom / 1e9
    buffer = (ctypes.c_uint8 * _RUSAGE_BUFFER_BYTES)()

    def field(offset: int) -> int:
        return int.from_bytes(bytes(buffer[offset:offset + 8]), sys.byteorder)

    def sample(pid: int) -> Optional[Tuple[float, int]]:
        if lib.proc_pid_rusage(pid, 0, ctypes.byref(buffer)) != 0:
            return None
        ticks = field(_USER_TIME_OFFSET) + field(_SYSTEM_TIME_OFFSET)
        return ticks * seconds_per_tick, field(_FOOTPRINT_OFFSET)

    return sample


def _linux_sampler() -> Sampler:
    page = os.sysconf("SC_PAGE_SIZE")
    ticks_per_second = os.sysconf("SC_CLK_TCK")

    def sample(pid: int) -> Optional[Tuple[float, int]]:
        try:
            with open(f"/proc/{pid}/statm", encoding="ascii") as handle:
                memory = int(handle.read().split()[1]) * page
            with open(f"/proc/{pid}/stat", encoding="ascii") as handle:
                # The name field may hold spaces, so count from its closing bracket.
                fields = handle.read().rsplit(")", 1)[1].split()
            return (int(fields[11]) + int(fields[12])) / ticks_per_second, memory
        except (OSError, ValueError, IndexError):
            return None

    return sample


def _make_sampler() -> Optional[Sampler]:
    if sys.platform == "darwin":
        return _darwin_sampler()
    if sys.platform.startswith("linux"):
        return _linux_sampler()
    return None


def _apply_rlimits(limits: Limits) -> None:
    """Runs in the child between fork and exec. Must not raise."""
    cpu = int(math.ceil(limits.time_s)) + 1
    settings = [
        (resource.RLIMIT_CPU, cpu),
        (resource.RLIMIT_CORE, 0),
        (resource.RLIMIT_FSIZE, limits.output_bytes),
        (resource.RLIMIT_NOFILE, limits.max_open_files),
    ]
    if limits.memory_mb is not None and sys.platform.startswith("linux"):
        settings.append((resource.RLIMIT_AS, limits.memory_mb * 1024 * 1024))
    for name, value in settings:
        try:
            resource.setrlimit(name, (value, value))
        except (ValueError, OSError):
            pass  # Enforcement falls back to the parent's monitor loop.


class _CappedReader(threading.Thread):
    """Drains a pipe, keeping at most ``limit`` bytes.

    Bytes beyond the cap are still read and dropped, so the child can never
    block on a full pipe; the monitor kills it once ``exceeded`` is set.
    """

    def __init__(self, stream: IO[bytes], limit: int) -> None:
        super().__init__(daemon=True)
        self.stream = stream
        self.limit = limit
        self.chunks: List[bytes] = []
        self.size = 0
        self.exceeded = False

    def run(self) -> None:
        while True:
            chunk = self.stream.read(65536)
            if not chunk:
                return
            remaining = self.limit - self.size
            if remaining > 0:
                self.chunks.append(chunk[:remaining])
            self.size += len(chunk)
            if self.size > self.limit:
                self.exceeded = True

    def text(self) -> str:
        return b"".join(self.chunks).decode("utf-8", errors="replace")


def _kill_group(process: "subprocess.Popen[bytes]") -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_process(
    argv: Sequence[str],
    limits: Limits,
    stdin_data: bytes = b"",
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    apply_rlimits: bool = True,
) -> ProcessResult:
    """Run ``argv`` to completion or until a limit trips.

    Each child leads its own process group so a timeout kills any descendants
    too. Stdin comes from a temporary file, which avoids pipe deadlocks when a
    program never reads its input.
    """
    sampler = _make_sampler()
    judge_cpu = limits.cpu_based and sampler is not None
    wall_limit = limits.time_s * WALL_BACKSTOP_FACTOR if judge_cpu else limits.time_s
    memory_limit_bytes = limits.memory_mb * 1024 * 1024 if limits.memory_mb else None
    peak = 0
    outcome: Optional[RunOutcome] = None
    started = time.monotonic()

    with tempfile.TemporaryFile() as stdin_file:
        stdin_file.write(stdin_data)
        stdin_file.seek(0)
        try:
            process = subprocess.Popen(
                list(argv),
                stdin=stdin_file,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env if env is not None else {},
                start_new_session=True,
                preexec_fn=(lambda: _apply_rlimits(limits)) if apply_rlimits else None,
                close_fds=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return ProcessResult(outcome=RunOutcome.FAILED_TO_START, error=str(error))

        out_reader = _CappedReader(process.stdout, limits.output_bytes)
        err_reader = _CappedReader(process.stderr, limits.output_bytes)
        out_reader.start()
        err_reader.start()

        while process.poll() is None:
            sample = sampler(process.pid) if sampler is not None else None
            cpu_seconds, footprint = sample if sample is not None else (0.0, 0)
            peak = max(peak, footprint)
            if time.monotonic() - started > wall_limit or (
                    judge_cpu and cpu_seconds > limits.time_s):
                outcome = RunOutcome.TIMEOUT
            elif out_reader.exceeded or err_reader.exceeded:
                outcome = RunOutcome.OUTPUT_LIMIT
            elif memory_limit_bytes is not None and footprint > memory_limit_bytes:
                outcome = RunOutcome.MEMORY_LIMIT
            if outcome is not None:
                _kill_group(process)
                break
            time.sleep(POLL_INTERVAL_S)

        try:
            process.wait(timeout=_KILL_REAP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            _kill_group(process)
            process.wait()
        duration = time.monotonic() - started
        # Sweep survivors of a normal exit: background children keep pipes open.
        _kill_group(process)
        out_reader.join(timeout=_KILL_REAP_TIMEOUT_S)
        err_reader.join(timeout=_KILL_REAP_TIMEOUT_S)

    code = process.returncode
    result = ProcessResult(
        outcome=outcome or RunOutcome.EXITED,
        stdout=out_reader.text(),
        stderr=err_reader.text(),
        stdout_truncated=out_reader.exceeded,
        stderr_truncated=err_reader.exceeded,
        duration_s=round(duration, 4),
        peak_memory_kb=(peak // 1024) if peak else None,
    )
    if outcome is None and out_reader.exceeded or outcome is None and err_reader.exceeded:
        result.outcome = RunOutcome.OUTPUT_LIMIT
    if code is not None and code < 0:
        result.signal = -code
        if outcome is None:
            result.outcome = _classify_signal(-code, limits)
    elif code is not None:
        result.exit_code = code
    return result


def _classify_signal(number: int, limits: Limits) -> RunOutcome:
    """Map a fatal signal to an outcome; the kernel's CPU limit is a timeout."""
    if number == signal.SIGXCPU:
        return RunOutcome.TIMEOUT
    if number == signal.SIGXFSZ:
        return RunOutcome.OUTPUT_LIMIT
    return RunOutcome.SIGNALED


def describe_signal(number: Optional[int]) -> str:
    if number is None:
        return "unknown signal"
    try:
        return signal.Signals(number).name
    except ValueError:
        return f"signal {number}"
