"""Loads test cases from disk and defines the output comparison policies.

A test is ``<id>.in`` plus ``<id>.out``, with an optional ``<id>.meta.json``
holding ``description``, ``time_limit_s``, and ``comparison``.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

COMPARISONS = ("exact", "trim_trailing", "normalize_whitespace")


@dataclass
class TestCase:
    test_id: str
    input: str = ""
    expected: Optional[str] = None
    description: str = ""
    time_limit_s: Optional[float] = None
    comparison: Optional[str] = None
    error: str = ""  # non-empty when the test itself is malformed


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace", newline="") as handle:
        return handle.read()


def _apply_meta(case: TestCase, path: str) -> None:
    try:
        with open(path, encoding="utf-8") as handle:
            meta = json.load(handle)
    except (OSError, ValueError) as error:
        case.error = f"unreadable metadata: {error}"
        return
    if not isinstance(meta, dict):
        case.error = "metadata must be a JSON object"
        return
    case.description = str(meta.get("description", ""))
    limit = meta.get("time_limit_s")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, (int, float))
                              or limit <= 0):
        case.error = f"invalid time_limit_s {limit!r}"
        return
    case.time_limit_s = limit
    comparison = meta.get("comparison")
    if comparison is not None and comparison not in COMPARISONS:
        case.error = f"unknown comparison {comparison!r}"
        return
    case.comparison = comparison


def load_testset(directory: str) -> List[TestCase]:
    """Return tests sorted by id. Malformed tests are kept, marked with ``error``."""
    if not os.path.isdir(directory):
        raise FileNotFoundError(f"test directory not found: {os.path.basename(directory)}")
    ids = set()
    for name in os.listdir(directory):
        if name.endswith(".in") or name.endswith(".out"):
            ids.add(name.rsplit(".", 1)[0])
    cases = []
    for test_id in sorted(ids):
        case = TestCase(test_id=test_id)
        in_path = os.path.join(directory, f"{test_id}.in")
        out_path = os.path.join(directory, f"{test_id}.out")
        if not os.path.isfile(in_path):
            case.error = "missing input file"
        elif not os.path.isfile(out_path):
            case.error = "missing expected-output file"
        if not case.error:
            try:
                case.input, case.expected = _read(in_path), _read(out_path)
            except OSError as error:
                case.error = f"unreadable test file: {error.strerror}"
        meta_path = os.path.join(directory, f"{test_id}.meta.json")
        if not case.error and os.path.isfile(meta_path):
            _apply_meta(case, meta_path)
        cases.append(case)
    return cases


def hash_testset(directory: str) -> Optional[str]:
    """Hash file names and contents, since the tests are part of 'the rules'."""
    if not os.path.isdir(directory):
        return None
    digest = hashlib.sha256()
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            digest.update(name.encode("utf-8") + b"\0")
            with open(path, "rb") as handle:
                digest.update(handle.read() + b"\0")
    return "sha256:" + digest.hexdigest()


def _trim(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()).rstrip("\n")


def compare_output(expected: str, actual: str, mode: str) -> Tuple[bool, str]:
    """Compare under a policy. Returns (matches, note).

    The note records any difference a lenient policy forgave, so nothing is
    silently ignored.
    """
    if expected == actual:
        return True, ""
    if mode == "exact":
        return False, ""
    if mode == "trim_trailing":
        if _trim(expected) == _trim(actual):
            return True, "accepted: differs only in trailing whitespace"
        return False, ""
    if expected.split() == actual.split():
        return True, "accepted: differs only in whitespace"
    return False, ""


def parameter_time(case_limit: Optional[float], default: float) -> float:
    return case_limit if case_limit is not None else default


def summarize_statuses(statuses: List[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for status in statuses:
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))
