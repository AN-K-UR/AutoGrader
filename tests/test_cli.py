import json
import unittest.mock as mock

import pytest

from execution.sandbox import SeatbeltBackend, DockerBackend
import main as cli


def run(*args):
    return cli.main(list(args))


def test_version(capsys):
    assert run("version") == 0
    assert "AutoGrader 1.0.0" in capsys.readouterr().out


def test_help_exits_cleanly():
    with pytest.raises(SystemExit) as caught:
        run("--help")
    assert caught.value.code == 0


def test_validate_config_success(capsys):
    assert run("validate-config", "--config", "config/rules.json") == 0
    assert "OK" in capsys.readouterr().out


def test_invalid_config_exit_code(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    assert run("validate-config", "--config", str(bad)) == cli.EXIT_CONFIG
    assert "not valid JSON" in capsys.readouterr().err


def test_list_tests(capsys):
    assert run("list-tests", "--config", "config/rules.json") == 0
    assert "10 test(s)" in capsys.readouterr().out


def test_list_tests_with_missing_directory(capsys):
    assert run("list-tests", "--tests", "/nonexistent") == cli.EXIT_CONFIG


def test_check_tools_runs_with_nothing_optional(capsys):
    with mock.patch("main.find_tool", return_value=None):
        assert run("check-tools") == 0
    assert "cppcheck" in capsys.readouterr().out


def test_grade_writes_both_reports(tmp_path, capsys):
    code = run("grade", "--source", "submissions/examples/add_correct.c",
               "--config", "config/rules.json", "--output", str(tmp_path), "--no-llm")
    assert code == 0
    report = json.loads((tmp_path / "add_correct.json").read_text())
    assert f"{report['grade']:.2f} / 100" in (tmp_path / "add_correct.txt").read_text()


def test_tests_flag_overrides_the_rules(tmp_path, capsys):
    tests = tmp_path / "t"
    tests.mkdir()
    (tests / "1.in").write_text("1 1\n")
    (tests / "1.out").write_text("2\n")
    run("grade", "--source", "submissions/examples/add_correct.c",
        "--tests", str(tests), "--output", str(tmp_path), "--no-llm")
    report = json.loads((tmp_path / "add_correct.json").read_text())
    assert report["metrics"][0]["evidence"]["tests_total"] == 1


def test_missing_submission_exit_code(tmp_path, capsys):
    code = run("grade", "--source", "absent.c", "--output", str(tmp_path))
    assert code == cli.EXIT_SUBMISSION


def test_no_secure_backend_refuses(tmp_path, capsys):
    with mock.patch.object(DockerBackend, "available", return_value=(False, "absent")), \
            mock.patch.object(SeatbeltBackend, "available", return_value=(False, "absent")):
        code = run("grade", "--source", "submissions/examples/add_correct.c",
                   "--output", str(tmp_path))
    assert code == cli.EXIT_NO_SANDBOX
    assert "no secure execution backend" in capsys.readouterr().err


def test_unsafe_mode_is_labelled_in_the_report(tmp_path, capsys):
    run("grade", "--source", "submissions/examples/add_correct.c", "--allow-unsafe",
        "--output", str(tmp_path), "--no-llm")
    report = json.loads((tmp_path / "add_correct.json").read_text())
    assert report["execution"]["name"] == "unsafe" and not report["execution"]["isolated"]
    assert "WITHOUT isolation" in (tmp_path / "add_correct.txt").read_text()


def test_verify_repro(capsys):
    code = run("verify-repro", "--source", "submissions/examples/add_student.c", "--runs", "2")
    assert code == 0
    assert "REPRODUCIBLE" in capsys.readouterr().out


def test_internal_error_exit_code(capsys):
    with mock.patch("main.load_rules", side_effect=RuntimeError("boom")):
        assert run("validate-config") == cli.EXIT_INTERNAL
