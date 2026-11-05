"""The web interface: same grades as the CLI, and closed to everything but this machine."""
import http.client
import json
import os
import threading
import unittest.mock as mock

import pytest

from agent.config_loader import load_rules
from agent.coordinator import evaluate
from execution.sandbox import SandboxUnavailable
from web.server import grade_submission, make_server, safe_file_name

SAMPLE = "submissions/examples/add_student.c"


@pytest.fixture(scope="module")
def port():
    server = make_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def request(port, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    sent = {"Content-Type": "application/json"} if body is not None else {}
    sent.update(headers or {})
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body)
    connection.request(method, path, data, sent)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    return response, raw


def payload(**changes):
    with open(SAMPLE, encoding="utf-8") as handle:
        document = {"filename": "add_student.c", "source": handle.read(),
                    "rules": "rules.json", "use_llm": False}
    document.update(changes)
    return document


def test_page_and_assets_are_served_with_a_strict_policy(port):
    for path, kind in (("/", "text/html"), ("/app.js", "javascript"), ("/style.css", "css")):
        response, _ = request(port, "GET", path)
        assert response.status == 200 and kind in response.getheader("Content-Type")
    policy = response.getheader("Content-Security-Policy")
    assert "default-src 'none'" in policy and "unsafe-inline" not in policy


def test_page_needs_nothing_from_the_internet():
    for name in ("index.html", "app.js", "style.css"):
        with open(os.path.join("web", "static", name), encoding="utf-8") as handle:
            text = handle.read().replace("http://www.w3.org/2000/svg", "")
        assert "http://" not in text and "https://" not in text


def test_untrusted_text_never_becomes_html():
    with open("web/static/app.js", encoding="utf-8") as handle:
        script = handle.read()
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert forbidden not in script


def test_rules_samples_and_status(port):
    rules = json.loads(request(port, "GET", "/api/rules")[1])
    assert {item["file"] for item in rules} >= {"rules.json", "rules_sort.json"}
    samples = json.loads(request(port, "GET", "/api/samples")[1])
    assert len(samples) == 18
    assert next(item for item in samples if item["name"] == "sort_bubble.c")["rules"] == "rules_sort.json"
    status = json.loads(request(port, "GET", "/api/status")[1])
    assert "sandbox" in status and status["ollama"]["status"] in ("ok", "unavailable")


def test_grade_matches_the_cli_path(port):
    response, raw = request(port, "POST", "/api/grade", payload())
    assert response.status == 200
    body = json.loads(raw)
    direct = evaluate(SAMPLE, load_rules("config/rules.json"), allow_llm=False)
    assert body["report"]["grade"] == direct.summary.grade
    assert body["report"]["grade_fingerprint"] == direct.fingerprint()
    assert f"Overall grade: {body['report']['grade']:.2f} / 100" in body["text"]
    assert "/Users/" not in raw.decode("utf-8")


def test_broken_submission_is_a_report_not_an_error(port):
    response, raw = request(port, "POST", "/api/grade",
                            payload(source="int main(void) { return 0 }\n"))
    assert response.status == 200
    assert json.loads(raw)["report"]["first_pass"]["compiled"] is False


def test_llm_is_off_unless_requested():
    with mock.patch("web.server.evaluate", side_effect=RuntimeError("stop")) as run:
        with pytest.raises(RuntimeError):
            grade_submission(payload(use_llm="yes"))
    assert run.call_args.kwargs["allow_llm"] is False


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "127.0.0.1:1"])
def test_foreign_host_is_rejected(port, host):
    assert request(port, "GET", "/api/rules", headers={"Host": host})[0].status == 403


def test_cross_site_post_is_rejected(port):
    response, _ = request(port, "POST", "/api/grade", payload(),
                          {"Origin": "https://evil.example"})
    assert response.status == 403


def test_same_origin_post_is_accepted(port):
    response, _ = request(port, "POST", "/api/grade", payload(),
                          {"Origin": f"http://127.0.0.1:{port}"})
    assert response.status == 200


def test_form_encoded_post_is_rejected(port):
    response, _ = request(port, "POST", "/api/grade", b"a=b",
                          {"Content-Type": "application/x-www-form-urlencoded"})
    assert response.status == 415


@pytest.mark.parametrize("rules", ["../../etc/passwd", "/etc/passwd", "missing.json", None])
def test_rule_set_cannot_be_a_path(port, rules):
    assert request(port, "POST", "/api/grade", payload(rules=rules))[0].status == 400


@pytest.mark.parametrize("path", ["/../main.py", "/web/server.py", "/config/rules.json", "/%2e%2e/main.py"])
def test_only_listed_files_are_served(port, path):
    assert request(port, "GET", path)[0].status == 404


def test_oversized_and_invalid_bodies(port):
    assert request(port, "POST", "/api/grade", payload(source="x" * 1_000_001))[0].status == 413
    assert request(port, "POST", "/api/grade", b"{not json")[0].status == 400
    assert request(port, "POST", "/api/grade", b"[]")[0].status == 400
    assert request(port, "POST", "/api/grade", payload(source="   "))[0].status == 400


def test_file_names_are_reduced_to_plain_names():
    assert safe_file_name("../../etc/x.c") == "x.c"
    assert safe_file_name("C:\\work\\my prog.c") == "my_prog.c"
    assert safe_file_name("$(touch ran);.c") == "__touch_ran__.c"
    for bad in ("notes.txt", ".c", None, ""):
        with pytest.raises(ValueError):
            safe_file_name(bad)


def test_missing_sandbox_refuses_and_never_falls_back(port):
    with mock.patch("web.server.evaluate", side_effect=SandboxUnavailable("no sandbox")) as run:
        response, raw = request(port, "POST", "/api/grade", payload())
    assert response.status == 503 and "no sandbox" in raw.decode()
    assert "allow_unsafe" not in run.call_args.kwargs


def test_server_binds_to_loopback_only(port):
    server = make_server(0)
    assert server.server_address[0] == "127.0.0.1"
    server.server_close()


def test_internal_failure_does_not_leak_details(port):
    with mock.patch("web.server.evaluate", side_effect=RuntimeError("/Users/secret/path")):
        response, raw = request(port, "POST", "/api/grade", payload())
    assert response.status == 500 and "secret" not in raw.decode()
