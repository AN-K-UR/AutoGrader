"""Local web interface. A thin layer over the same agent the CLI uses.

Uses only the standard library so the demo works offline. It is for one person on
one computer: it binds to loopback, and there is no login, so it must never be
exposed to a network. Grading always goes through a secure backend; unlike the CLI
there is deliberately no way to request the unsafe one from here.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Tuple

from agent.config_loader import ConfigError, load_rules
from agent.coordinator import MAX_SOURCE_BYTES, SubmissionError, evaluate
from analyzers.llm_client import ollama_status
from execution.sandbox import DockerBackend, SandboxUnavailable, SeatbeltBackend
from reporting.json_report import build_report
from reporting.text_report import render_text

log = logging.getLogger("autograder")

HOST = "127.0.0.1"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATIC_DIR = os.path.join(PROJECT_ROOT, "web", "static")
_STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
# The page shows untrusted program output. Scripts load only from this server, so
# even a rendering mistake could not run anything a submission printed.
_CONTENT_SECURITY_POLICY = ("default-src 'none'; script-src 'self'; style-src 'self'; "
                            "connect-src 'self'; base-uri 'none'; form-action 'none'; "
                            "frame-ancestors 'none'")
_MAX_BODY_BYTES = MAX_SOURCE_BYTES * 2  # JSON escaping can inflate the source.
_UNSAFE_NAME_CHARACTERS = re.compile(r"[^\w.-]")
# Execution analyzers must never overlap, or load could change a borderline grade.
_grading_lock = threading.Lock()


class RequestError(ValueError):
    """A bad request, with the HTTP status to answer it with."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _rules_paths() -> Dict[str, str]:
    paths = glob.glob(os.path.join(PROJECT_ROOT, "config", "rules*.json"))
    return {os.path.basename(path): path for path in sorted(paths)}


def list_rules() -> List[Dict[str, Any]]:
    """Valid rule sets, for the page's menu."""
    available = []
    for name, path in _rules_paths().items():
        try:
            rules = load_rules(path)
            with open(path, encoding="utf-8") as handle:
                description = json.load(handle).get("description", "")
        except ConfigError as error:
            log.warning("skipping %s: %s", name, error)
            continue
        available.append({
            "file": name, "problem": rules.problem, "description": description,
            "time_limit_s": rules.time_limit_s, "memory_limit_mb": rules.memory_limit_mb,
            "metrics": [{"name": metric.name, "weight": metric.weight}
                        for metric in rules.metrics if metric.enabled],
        })
    return available


def list_samples() -> List[Dict[str, str]]:
    samples = []
    for path in sorted(glob.glob(os.path.join(PROJECT_ROOT, "submissions", "examples", "*.c"))):
        name = os.path.basename(path)
        with open(path, encoding="utf-8", errors="replace") as handle:
            samples.append({"name": name, "source": handle.read(),
                            "rules": "rules_sort.json" if name.startswith("sort_")
                                     else "rules.json"})
    return samples


def system_status() -> Dict[str, Any]:
    for backend in (DockerBackend(), SeatbeltBackend()):
        usable, _ = backend.available()
        if usable:
            sandbox = {"name": backend.name, "guarantees": backend.guarantees}
            break
    else:
        sandbox = None
    return {"sandbox": sandbox, "ollama": ollama_status()}


def safe_file_name(name: Any) -> str:
    """Reduce a browser-supplied name to a plain ``.c`` file name."""
    if not isinstance(name, str):
        raise RequestError(400, "the file name is missing")
    cleaned = _UNSAFE_NAME_CHARACTERS.sub("_", os.path.basename(name.replace("\\", "/")))[-100:]
    if not cleaned.endswith(".c") or cleaned == ".c":
        raise RequestError(400, "please submit a .c file")
    return cleaned


def grade_submission(payload: Any) -> Dict[str, Any]:
    """Grade source sent by the page. Returns the report and its text form."""
    if not isinstance(payload, dict):
        raise RequestError(400, "the request must be a JSON object")
    name = safe_file_name(payload.get("filename"))
    source = payload.get("source")
    if not isinstance(source, str) or not source.strip():
        raise RequestError(400, "the submission is empty")
    encoded = source.encode("utf-8")
    if len(encoded) > MAX_SOURCE_BYTES:
        raise RequestError(413, f"the submission is larger than {MAX_SOURCE_BYTES} bytes")
    # Looked up in a fixed list, so this can never be used to open another path.
    rules_path = _rules_paths().get(payload.get("rules"))
    if rules_path is None:
        raise RequestError(400, "unknown rule set")

    rules = load_rules(rules_path)
    with tempfile.TemporaryDirectory(prefix="autograder-upload-") as directory:
        path = os.path.join(directory, name)
        with open(path, "wb") as handle:
            handle.write(encoded)
        with _grading_lock:
            evaluation = evaluate(path, rules, allow_llm=payload.get("use_llm") is True)
    report = build_report(evaluation)
    return {"report": report, "text": render_text(report)}


class Handler(BaseHTTPRequestHandler):
    server_version = "AutoGrader"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        log.info("%s %s", self.address_string(), format % args)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, value: Any) -> None:
        self._send(status, json.dumps(value).encode("utf-8"), "application/json; charset=utf-8")

    def _allowed_hosts(self) -> Tuple[str, str]:
        port = self.server.server_address[1]
        return f"127.0.0.1:{port}", f"localhost:{port}"

    def _reject_foreign_request(self) -> bool:
        """Stop other websites reaching this server through the user's browser.

        The Host check defeats DNS rebinding, and the Origin check stops a page
        elsewhere from posting a request here.
        """
        allowed = self._allowed_hosts()
        origin = self.headers.get("Origin")
        if self.headers.get("Host") not in allowed or (
                origin is not None and origin not in tuple(f"http://{item}" for item in allowed)):
            self._send_json(403, {"error": "this server only accepts local requests"})
            return True
        return False

    def do_GET(self) -> None:  # noqa: N802
        if self._reject_foreign_request():
            return
        path = self.path.split("?", 1)[0]
        routes = {"/api/rules": list_rules, "/api/samples": list_samples,
                  "/api/status": system_status}
        if path in routes:
            self._send_json(200, routes[path]())
        elif path in _STATIC_FILES:
            name, content_type = _STATIC_FILES[path]
            with open(os.path.join(_STATIC_DIR, name), "rb") as handle:
                self._send(200, handle.read(), content_type)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self._reject_foreign_request():
            return
        if self.path != "/api/grade":
            self._send_json(404, {"error": "not found"})
            return
        try:
            self._send_json(200, grade_submission(self._read_json()))
        except RequestError as error:
            self._send_json(error.status, {"error": str(error)})
        except (SubmissionError, ConfigError) as error:
            self._send_json(400, {"error": str(error)})
        except SandboxUnavailable as error:
            self._send_json(503, {"error": str(error)})
        except Exception:  # pylint: disable=broad-except
            log.exception("grading failed")
            self._send_json(500, {"error": "grading failed; see the server's terminal"})

    def _read_json(self) -> Any:
        # A cross-site form cannot send this type without a preflight we never answer.
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise RequestError(415, "expected application/json")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError as error:
            raise RequestError(411, "a content length is required") from error
        if not 0 <= length <= _MAX_BODY_BYTES:
            raise RequestError(413, "the request is too large")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise RequestError(400, "the request is not valid JSON") from error


def make_server(port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((HOST, port), Handler)


def serve(port: int) -> None:
    server = make_server(port)
    print(f"AutoGrader is running at http://{HOST}:{server.server_address[1]}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
