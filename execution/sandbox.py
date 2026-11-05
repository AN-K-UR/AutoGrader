"""Execution backends: where untrusted compilers and binaries actually run.

Grading logic only ever sees :class:`ExecutionBackend`, so swapping the backend
needs no change elsewhere. Backends and what they really provide:

* ``seatbelt``  macOS ``sandbox-exec``. Verified here: writes, fork, exec of other
  programs, network connections, and reads outside system paths are denied.
* ``docker``    Linux container with no network, no capabilities, read-only root.
  Implemented, but no Docker was available during development, so only its
  command construction has been tested.
* ``unsafe``    No isolation at all. Requires an explicit opt-in and is labelled
  as such in every report.

``sandbox-exec`` is deprecated by Apple and none of these is a guarantee against
a determined attacker. See SECURITY.md.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Sequence, Set, Tuple

from execution.process_runner import Limits, run_process
from models.results import ProcessResult, RunOutcome

_SAFE_ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"}
_TOOL_TIMEOUT_S = 10.0

# Applied to the student's binary: nothing is allowed unless listed.
_RUN_PROFILE = """(version 1)
(deny default)
(allow process-exec (literal (param "BINARY")))
(allow file-read-metadata)
(allow file-read* (subpath "/usr/lib") (subpath "/System") (literal "/")
                  (subpath "/private/var/db/dyld") (subpath "/dev")
                  (subpath "/Library/Developer") (subpath (param "WORK")))
(allow file-write* (literal "/dev/null"))
(allow sysctl-read)
(allow mach-lookup (global-name "com.apple.system.notification_center"))
"""

# The compiler may fork its own tools and write to the work directory only. It
# cannot read the user's files, so ``#include "/Users/x/.ssh/id_rsa"`` fails
# instead of leaking the file through a diagnostic.
_COMPILE_PROFILE = """(version 1)
(deny default)
(allow process-fork)
(allow process-exec (subpath "/usr") (subpath "/Library/Developer")
                    (subpath "/Applications/Xcode.app"))
(allow file-read-metadata)
(allow file-read* (subpath "/usr") (subpath "/System") (subpath "/Library/Developer")
                  (subpath "/Applications/Xcode.app") (subpath "/private/var/db/dyld")
                  (subpath "/dev") (literal "/"))
(allow file-read* file-write* (subpath (param "WORK")))
(allow file-write* (literal "/dev/null"))
(allow sysctl-read)
(allow mach-lookup)
(allow ipc-posix-shm)
"""


class SandboxUnavailable(RuntimeError):
    """No backend meeting the configured safety requirement exists here."""


class ExecutionBackend(ABC):
    name = "abstract"
    isolated = False
    guarantees = ""

    @abstractmethod
    def available(self) -> Tuple[bool, str]:
        """Return (usable, reason)."""

    @abstractmethod
    def run_compiler(self, compiler: str, args: Sequence[str], workdir: str,
                     timeout_s: float) -> ProcessResult:
        """Run a compiler in ``workdir``, which is the only writable location."""

    @abstractmethod
    def run_binary(self, binary: str, limits: Limits, stdin_data: bytes, workdir: str,
                   env: Optional[Dict[str, str]] = None) -> ProcessResult:
        """Run a compiled submission under ``limits``."""

    def compiler_version(self, compiler: str, workdir: str) -> str:
        result = self.run_compiler(compiler, ["--version"], workdir, _TOOL_TIMEOUT_S)
        lines = (result.stdout or result.stderr).strip().splitlines()
        return lines[0] if lines else "unknown"


def _compile_limits(timeout_s: float) -> Limits:
    # A compiler's memory use is not the submission's; the time limit still
    # stops pathological inputs such as template-like macro explosions.
    return Limits(time_s=timeout_s, memory_mb=None, output_bytes=2_000_000,
                  max_open_files=256, cpu_based=False)


class SeatbeltBackend(ExecutionBackend):
    name = "seatbelt"
    isolated = True
    guarantees = ("macOS sandbox-exec: file writes, fork/exec of other programs, network "
                  "connections and reads outside system paths are denied for the program; "
                  "memory enforced by polling the physical footprint")

    def __init__(self) -> None:
        self._launched: Set[str] = set()

    def available(self) -> Tuple[bool, str]:
        if sys.platform != "darwin":
            return False, "sandbox-exec exists only on macOS"
        if shutil.which("sandbox-exec") is None:
            return False, "sandbox-exec not found"
        return True, "sandbox-exec found"

    def _resolve_compiler(self, compiler: str) -> Tuple[str, List[str]]:
        """Resolve Apple's /usr/bin shims, which cannot run under this profile."""
        if shutil.which("xcrun") is None:
            return compiler, []
        path = _capture(["xcrun", "-f", "clang"])
        sdk = _capture(["xcrun", "--show-sdk-path"])
        if not path:
            return compiler, []
        return path, ["-isysroot", sdk] if sdk else []

    def run_compiler(self, compiler: str, args: Sequence[str], workdir: str,
                     timeout_s: float) -> ProcessResult:
        resolved = shutil.which(compiler)
        if resolved is None:
            return ProcessResult(outcome=RunOutcome.FAILED_TO_START,
                                 error=f"compiler not found: {compiler}")
        extra: List[str] = []
        if resolved.startswith("/usr/bin/"):
            resolved, extra = self._resolve_compiler(compiler)
        if "--version" in args:
            extra = []
        work = os.path.realpath(workdir)
        argv = ["sandbox-exec", "-D", f"WORK={work}", "-p", _COMPILE_PROFILE,
                resolved, *extra, *args]
        env = dict(_SAFE_ENV, TMPDIR=work + "/", HOME=work)
        return run_process(_absolute(argv), _compile_limits(timeout_s), cwd=work, env=env,
                           apply_rlimits=False)

    def run_binary(self, binary: str, limits: Limits, stdin_data: bytes, workdir: str,
                   env: Optional[Dict[str, str]] = None) -> ProcessResult:
        work = os.path.realpath(workdir)
        path = os.path.realpath(os.path.join(work, binary))
        argv = ["sandbox-exec", "-D", f"WORK={work}", "-D", f"BINARY={path}",
                "-p", _RUN_PROFILE, path]
        run_env = dict(_SAFE_ENV, **(env or {}))
        result = run_process(_absolute(argv), limits, stdin_data, cwd=work, env=run_env)
        # macOS spends 0.2-0.6 s vetting a binary on its first launch (measured;
        # later launches take about 15 ms). Without this retry a first launch
        # could time out where a second would not, making the grade depend on luck.
        cold_start = path not in self._launched
        self._launched.add(path)
        if cold_start and result.outcome == RunOutcome.TIMEOUT:
            result = run_process(_absolute(argv), limits, stdin_data, cwd=work, env=run_env)
        return result


class DockerBackend(ExecutionBackend):
    name = "docker"
    isolated = True
    guarantees = ("Linux container: no network, non-root, all capabilities dropped, "
                  "read-only root, CPU/memory/process limits. Shares the host kernel.")

    def __init__(self, image: str = "autograder-sandbox:latest") -> None:
        self.image = image

    def available(self) -> Tuple[bool, str]:
        if shutil.which("docker") is None:
            return False, "docker not found"
        try:
            info = subprocess.run(["docker", "image", "inspect", self.image],
                                  capture_output=True, timeout=_TOOL_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError) as error:
            return False, f"docker not responding: {error}"
        if info.returncode != 0:
            return False, f"image {self.image} missing or daemon stopped; see SECURITY.md"
        return True, "docker image found"

    def base_command(self, workdir: str, name: str, memory_mb: int, pids: int,
                     writable_work: bool, env: Optional[Dict[str, str]] = None) -> List[str]:
        """Build the hardened ``docker run`` prefix. Separated so it can be tested."""
        mode = "rw" if writable_work else "ro"
        command = [
            "docker", "run", "--rm", "--interactive", "--name", name,
            "--network", "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", "65534:65534",
            "--pids-limit", str(pids),
            "--memory", f"{memory_mb}m",
            "--memory-swap", f"{memory_mb}m",
            "--cpus", "1",
            "--ulimit", "core=0",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
            "--volume", f"{os.path.realpath(workdir)}:/work:{mode}",
            "--workdir", "/work",
        ]
        for key, value in sorted((env or {}).items()):
            command += ["--env", f"{key}={value}"]
        return command + [self.image]

    def _run(self, command: List[str], name: str, limits: Limits,
             stdin_data: bytes = b"") -> ProcessResult:
        # The docker client is trusted, so the limits below apply to the wait,
        # and a timeout must also kill the container, not just the client.
        client_limits = Limits(time_s=limits.time_s + 2.0, memory_mb=None,
                               output_bytes=limits.output_bytes, max_open_files=256,
                               cpu_based=False)
        result = run_process(command, client_limits, stdin_data,
                             env=dict(os.environ), apply_rlimits=False)
        if result.outcome in (RunOutcome.TIMEOUT, RunOutcome.OUTPUT_LIMIT):
            subprocess.run(["docker", "kill", name], capture_output=True,
                           timeout=_TOOL_TIMEOUT_S, check=False)
        elif result.exit_code == 137:
            result.outcome = RunOutcome.MEMORY_LIMIT
        return result

    def run_compiler(self, compiler: str, args: Sequence[str], workdir: str,
                     timeout_s: float) -> ProcessResult:
        name = f"autograder-{uuid.uuid4().hex[:12]}"
        command = self.base_command(workdir, name, 1024, 64, writable_work=True)
        return self._run(command + [compiler, *args], name, _compile_limits(timeout_s))

    def run_binary(self, binary: str, limits: Limits, stdin_data: bytes, workdir: str,
                   env: Optional[Dict[str, str]] = None) -> ProcessResult:
        name = f"autograder-{uuid.uuid4().hex[:12]}"
        command = self.base_command(workdir, name, limits.memory_mb or 1024,
                                    limits.max_processes, writable_work=False, env=env)
        return self._run(command + [f"/work/{binary}"], name, limits, stdin_data)


class UnsafeBackend(ExecutionBackend):
    """Direct execution with rlimits only. This is not a sandbox."""

    name = "unsafe"
    isolated = False
    guarantees = ("NONE. Runs with the full privileges of the current user; only time, "
                  "memory and output limits apply. Trusted code only.")

    def available(self) -> Tuple[bool, str]:
        return True, "always available; requires explicit opt-in"

    def run_compiler(self, compiler: str, args: Sequence[str], workdir: str,
                     timeout_s: float) -> ProcessResult:
        resolved = shutil.which(compiler)
        if resolved is None:
            return ProcessResult(outcome=RunOutcome.FAILED_TO_START,
                                 error=f"compiler not found: {compiler}")
        env = dict(_SAFE_ENV, TMPDIR=os.path.realpath(workdir) + "/", HOME=workdir)
        return run_process([resolved, *args], _compile_limits(timeout_s), cwd=workdir,
                           env=env, apply_rlimits=False)

    def run_binary(self, binary: str, limits: Limits, stdin_data: bytes, workdir: str,
                   env: Optional[Dict[str, str]] = None) -> ProcessResult:
        return run_process([os.path.join(os.path.realpath(workdir), binary)], limits,
                           stdin_data, cwd=workdir, env=dict(_SAFE_ENV, **(env or {})))


def _absolute(argv: List[str]) -> List[str]:
    """Popen with an empty PATH cannot find bare names, so pin sandbox-exec."""
    found = shutil.which(argv[0])
    return [found or argv[0], *argv[1:]]


def _capture(argv: List[str]) -> str:
    try:
        done = subprocess.run(argv, capture_output=True, text=True,
                              timeout=_TOOL_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def select_backend(preference: str, docker_image: str, allow_unsafe: bool) -> ExecutionBackend:
    """Choose a backend, refusing rather than silently losing isolation."""
    if preference == "unsafe" or allow_unsafe:
        if not allow_unsafe:
            raise SandboxUnavailable(
                "rules ask for the unsafe backend, but --allow-unsafe was not given")
        return UnsafeBackend()
    candidates: List[ExecutionBackend] = {
        "auto": [DockerBackend(docker_image), SeatbeltBackend()],
        "docker": [DockerBackend(docker_image)],
        "seatbelt": [SeatbeltBackend()],
    }[preference]
    reasons = []
    for backend in candidates:
        usable, reason = backend.available()
        if usable:
            return backend
        reasons.append(f"{backend.name}: {reason}")
    raise SandboxUnavailable(
        "no secure execution backend is available (" + "; ".join(reasons) + "). "
        "Install Docker, or pass --allow-unsafe for trusted code only.")
