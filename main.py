#!/usr/bin/env python3
"""AutoGrader command-line interface.

Exit codes: 0 finished, 1 internal failure, 2 invalid rules or arguments,
3 unusable submission, 4 no secure backend, 5 reproducibility check failed.
"""
from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import shutil
import sys
from typing import List, Optional

from agent.config_loader import ConfigError, Rules, load_rules
from agent.coordinator import SubmissionError, evaluate
from analyzers.base import registered_analyzers
from analyzers.static_analysis import find_tool
from analyzers.testset import load_testset
from execution.sandbox import DockerBackend, SandboxUnavailable, SeatbeltBackend
from reporting.json_report import build_report, write_json
from reporting.text_report import render_text, write_text

__version__ = "1.0.0"

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_CONFIG = 2
EXIT_SUBMISSION = 3
EXIT_NO_SANDBOX = 4
EXIT_NOT_REPRODUCIBLE = 5


def _apply_overrides(rules: Rules, tests: Optional[str]) -> Rules:
    """``--tests`` replaces every test directory the rules name."""
    if not tests:
        return rules
    absolute = os.path.abspath(tests)
    metrics = [dataclasses.replace(metric, params=dict(metric.params, testset_dir=absolute))
               if "testset_dir" in metric.params else metric for metric in rules.metrics]
    return dataclasses.replace(rules, metrics=metrics)


def command_grade(args: argparse.Namespace) -> int:
    rules = _apply_overrides(load_rules(args.config), args.tests)
    evaluation = evaluate(args.source, rules, allow_unsafe=args.allow_unsafe,
                          keep_workspace=args.keep_temp, allow_llm=not args.no_llm)
    report = build_report(evaluation)
    os.makedirs(args.output, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.source))[0]
    json_path = os.path.join(args.output, f"{stem}.json")
    text_path = os.path.join(args.output, f"{stem}.txt")
    write_json(report, json_path)
    write_text(report, text_path)
    grade = report["grade"]
    shown = "not gradable" if grade is None else f"{grade:.2f} / 100"
    print(f"{stem}: {shown} [{report['evaluation_status']}]")
    print(f"  {json_path}\n  {text_path}")
    if args.print_report:
        print(render_text(report))
    return EXIT_OK


def command_validate(args: argparse.Namespace) -> int:
    rules = load_rules(args.config)
    enabled = [metric for metric in rules.metrics if metric.enabled]
    print(f"OK: {args.config} is valid ({rules.problem}, {len(enabled)} enabled metrics, "
          f"weights sum to {sum(metric.weight for metric in enabled):g})")
    print(f"hash: {rules.hash}")
    return EXIT_OK


def command_list_tests(args: argparse.Namespace) -> int:
    rules = _apply_overrides(load_rules(args.config), args.tests)
    directory = rules.first_testset()
    if directory is None:
        print("These rules name no test directory.")
        return EXIT_OK
    cases = load_testset(directory)
    print(f"{len(cases)} test(s) in {directory}")
    for case in cases:
        note = f"MALFORMED: {case.error}" if case.error else case.description
        print(f"  {case.test_id:<12} {note}")
    return EXIT_OK


def command_check_tools(_: argparse.Namespace) -> int:
    rows = []
    for name in ("gcc", "clang"):
        rows.append((name, shutil.which(name) or "not found", "compiles submissions"))
    rows.append(("cppcheck", find_tool("cppcheck") or "not found", "structure metric"))
    try:
        import lizard
        rows.append(("lizard", f"version {lizard.version}", "structure metric"))
    except ImportError:
        rows.append(("lizard", "not found", "structure metric"))
    rows.append(("ollama", shutil.which("ollama") or "not found", "optional advisory remarks"))
    for backend in (SeatbeltBackend(), DockerBackend()):
        usable, reason = backend.available()
        rows.append((f"backend:{backend.name}", ("ready: " if usable else "unavailable: ") + reason,
                     "isolated execution"))
    for name, state, purpose in rows:
        print(f"{name:<18}{state:<60}{purpose}")
    print("analyzers: " + ", ".join(registered_analyzers()))
    return EXIT_OK


def command_verify(args: argparse.Namespace) -> int:
    """Grade repeatedly and compare fingerprints: the contract, checked directly."""
    rules = load_rules(args.config)
    runs = []
    for _ in range(args.runs):
        evaluation = evaluate(args.source, rules, allow_unsafe=args.allow_unsafe, allow_llm=False)
        runs.append((evaluation.summary.grade, evaluation.fingerprint()))
        print(f"run {len(runs)}: grade {runs[-1][0]} fingerprint {runs[-1][1][:23]}...")
    if len(set(runs)) == 1:
        print(f"REPRODUCIBLE: {args.runs} runs produced the same grade")
        return EXIT_OK
    print("NOT REPRODUCIBLE: runs differed")
    return EXIT_NOT_REPRODUCIBLE


def command_serve(args: argparse.Namespace) -> int:
    from web.server import serve
    serve(args.port)
    return EXIT_OK


def command_version(_: argparse.Namespace) -> int:
    print(f"AutoGrader {__version__}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autograder", description="Rule-driven automatic evaluator for student C programs.")
    parser.add_argument("--verbose", action="store_true", help="show diagnostic logging")
    commands = parser.add_subparsers(dest="command", required=True)

    grade = commands.add_parser("grade", help="grade one submission")
    grade.add_argument("--source", required=True, help="student .c file")
    grade.add_argument("--config", default="config/rules.json", help="rules file")
    grade.add_argument("--tests", help="test directory, overriding the rules")
    grade.add_argument("--output", default="reports", help="report directory")
    grade.add_argument("--allow-unsafe", action="store_true",
                       help="run with NO isolation; for trusted code only")
    grade.add_argument("--no-llm", action="store_true", help="never contact a language model")
    grade.add_argument("--keep-temp", action="store_true", help="keep the work directory")
    grade.add_argument("--print-report", action="store_true", help="also print the text report")
    grade.set_defaults(handler=command_grade)

    validate = commands.add_parser("validate-config", help="validate a rules file")
    validate.add_argument("--config", default="config/rules.json")
    validate.set_defaults(handler=command_validate)

    listing = commands.add_parser("list-tests", help="list the test cases the rules use")
    listing.add_argument("--config", default="config/rules.json")
    listing.add_argument("--tests")
    listing.set_defaults(handler=command_list_tests)

    tools = commands.add_parser("check-tools", help="show which external tools are available")
    tools.set_defaults(handler=command_check_tools)

    verify = commands.add_parser("verify-repro", help="grade repeatedly and compare results")
    verify.add_argument("--source", required=True)
    verify.add_argument("--config", default="config/rules.json")
    verify.add_argument("--runs", type=int, default=3)
    verify.add_argument("--allow-unsafe", action="store_true")
    verify.set_defaults(handler=command_verify)

    web = commands.add_parser("serve", help="start the web interface on this computer")
    web.add_argument("--port", type=int, default=8000)
    web.set_defaults(handler=command_serve)

    version = commands.add_parser("version", help="show the version")
    version.set_defaults(handler=command_version)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s: %(message)s")
    try:
        return args.handler(args)
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return EXIT_CONFIG
    except FileNotFoundError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return EXIT_CONFIG
    except SubmissionError as error:
        print(f"Submission error: {error}", file=sys.stderr)
        return EXIT_SUBMISSION
    except SandboxUnavailable as error:
        print(f"Sandbox error: {error}", file=sys.stderr)
        return EXIT_NO_SANDBOX
    except Exception as error:  # pylint: disable=broad-except
        logging.getLogger("autograder").exception("internal failure")
        print(f"Internal error: {error}", file=sys.stderr)
        return EXIT_INTERNAL


if __name__ == "__main__":
    sys.exit(main())

