"""Isolation behaviour. The programs only attempt small, harmless actions."""
import os
import sys
import unittest.mock as mock

import pytest

from conftest import needs_seatbelt
from execution.compiler import compile_source
from execution.process_runner import Limits
from execution.sandbox import (DockerBackend, SandboxUnavailable, SeatbeltBackend, UnsafeBackend,
                               select_backend)
from models.results import RunOutcome

PROBE = """#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <arpa/inet.h>
int main(int argc, char **argv) {
    (void)argc; (void)argv;
    char mode[32] = {0};
    if (scanf("%31s", mode) != 1) return 9;
    if (!strcmp(mode, "read")) {
        char path[512] = {0};
        scanf("%511s", path);
        int fd = open(path, O_RDONLY);
        puts(fd >= 0 ? "allowed" : "blocked");
    } else if (!strcmp(mode, "write")) {
        char path[512] = {0};
        scanf("%511s", path);
        int fd = open(path, O_CREAT | O_WRONLY, 0600);
        puts(fd >= 0 ? "allowed" : "blocked");
    } else if (!strcmp(mode, "fork")) {
        pid_t child = fork();
        if (child == 0) _exit(0);
        puts(child >= 0 ? "allowed" : "blocked");
    } else if (!strcmp(mode, "shell")) {
        puts(system("/bin/echo ran") == 0 ? "allowed" : "blocked");
    } else if (!strcmp(mode, "connect")) {
        struct sockaddr_in target;
        int sock = socket(AF_INET, SOCK_STREAM, 0);
        memset(&target, 0, sizeof target);
        target.sin_family = AF_INET;
        target.sin_port = htons(9);
        inet_pton(AF_INET, "127.0.0.1", &target.sin_addr);
        int status = connect(sock, (void *)&target, sizeof target);
        puts(status != 0 && errno == EPERM ? "blocked" : "allowed");
    }
    return 0;
}
"""
MEMORY_HOG = """#include <stdlib.h>
#include <string.h>
#include <stdio.h>
int main(void) {
    size_t size = 512u << 20;
    char *block = malloc(size);
    if (block == NULL) { puts("refused"); return 0; }
    memset(block, 1, size);
    puts("allocated");
    return 0;
}
"""


@pytest.fixture
def probe(workdir):
    seatbelt = SeatbeltBackend()
    with open(f"{workdir}/probe.c", "w", encoding="utf-8") as handle:
        handle.write(PROBE)
    assert compile_source(seatbelt, "gcc", ["probe.c"], "probe.bin", ["-w"], workdir, 20).success

    def attempt(command):
        result = seatbelt.run_binary("probe.bin", Limits(time_s=5), command.encode(), workdir)
        return result.stdout.strip()
    return attempt


@needs_seatbelt
def test_cannot_read_outside_allowed_paths(probe):
    assert probe(f"read {os.path.abspath(__file__)}") == "blocked"


@needs_seatbelt
def test_can_read_its_own_work_directory(probe, workdir):
    assert probe(f"read {workdir}/probe.c") == "allowed"


@needs_seatbelt
def test_cannot_write_anywhere(probe, workdir, tmp_path):
    target = tmp_path / "written"
    assert probe(f"write {target}") == "blocked"
    assert not target.exists()
    assert probe(f"write {workdir}/new_file") == "blocked"


@needs_seatbelt
def test_cannot_fork(probe):
    assert probe("fork") == "blocked"


@needs_seatbelt
def test_cannot_start_a_shell(probe):
    assert probe("shell") == "blocked"


@needs_seatbelt
def test_cannot_connect_to_the_network(probe):
    assert probe("connect") == "blocked"


@needs_seatbelt
def test_memory_limit_enforced_in_the_sandbox(workdir):
    seatbelt = SeatbeltBackend()
    with open(f"{workdir}/hog.c", "w", encoding="utf-8") as handle:
        handle.write(MEMORY_HOG)
    assert compile_source(seatbelt, "gcc", ["hog.c"], "hog.bin", ["-w"], workdir, 20).success
    result = seatbelt.run_binary("hog.bin", Limits(time_s=10, memory_mb=64), b"", workdir)
    assert result.outcome == RunOutcome.MEMORY_LIMIT


@needs_seatbelt
def test_compiler_cannot_read_host_files_through_include(workdir):
    seatbelt = SeatbeltBackend()
    secret = os.path.abspath(__file__)
    with open(f"{workdir}/peek.c", "w", encoding="utf-8") as handle:
        handle.write(f'#include "{secret}"\nint main(void) {{ return 0; }}\n')
    result = compile_source(seatbelt, "gcc", ["peek.c"], "peek.bin", [], workdir, 20)
    assert not result.success
    assert "Operation not permitted" in result.output
    assert "needs_seatbelt" not in result.output


@needs_seatbelt
def test_cold_start_retry_keeps_a_real_hang_a_timeout(workdir):
    seatbelt = SeatbeltBackend()
    with open(f"{workdir}/spin.c", "w", encoding="utf-8") as handle:
        handle.write("int main(void) { volatile int on = 1; while (on) {} return 0; }\n")
    assert compile_source(seatbelt, "gcc", ["spin.c"], "spin.bin", [], workdir, 20).success
    result = seatbelt.run_binary("spin.bin", Limits(time_s=0.3), b"", workdir)
    assert result.outcome == RunOutcome.TIMEOUT


def test_auto_refuses_rather_than_downgrading():
    with mock.patch.object(DockerBackend, "available", return_value=(False, "absent")), \
            mock.patch.object(SeatbeltBackend, "available", return_value=(False, "absent")):
        with pytest.raises(SandboxUnavailable, match="no secure execution backend"):
            select_backend("auto", "image", allow_unsafe=False)


def test_unsafe_requires_explicit_flag():
    with pytest.raises(SandboxUnavailable, match="--allow-unsafe"):
        select_backend("unsafe", "image", allow_unsafe=False)
    backend = select_backend("unsafe", "image", allow_unsafe=True)
    assert isinstance(backend, UnsafeBackend) and not backend.isolated


def test_docker_preferred_when_ready():
    with mock.patch.object(DockerBackend, "available", return_value=(True, "ok")):
        assert select_backend("auto", "image", False).name == "docker"


def test_docker_command_is_hardened(tmp_path):
    command = DockerBackend().base_command(str(tmp_path), "name", 64, 16, writable_work=False)
    joined = " ".join(command)
    for expected in ("--network none", "--read-only", "--cap-drop ALL", "--pids-limit 16",
                     "--memory 64m", "--memory-swap 64m", "no-new-privileges",
                     "--user 65534:65534", ":/work:ro"):
        assert expected in joined
    assert "--privileged" not in joined


def test_docker_compile_needs_writable_work_only(tmp_path):
    command = DockerBackend().base_command(str(tmp_path), "n", 64, 16, writable_work=True)
    assert any(item.endswith(":/work:rw") for item in command)


def test_docker_unavailable_when_binary_missing():
    with mock.patch("execution.sandbox.shutil.which", return_value=None):
        assert DockerBackend().available()[0] is False


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_seatbelt_reports_available_on_macos():
    assert SeatbeltBackend().available()[0] is True
