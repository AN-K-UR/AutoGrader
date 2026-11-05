"""Loads and validates the instructor's rules file.

The file format is the one in the assignment (``problem``, ``time_limit_s``,
``memory_limit_mb``, ``metrics``) plus optional sections with safe defaults.
Paths are resolved relative to the rules file so that a grade never depends on
the directory the agent was started from.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from analyzers.base import get_analyzer, registered_analyzers

_WEIGHT_TOLERANCE = 1e-6

DEFAULTS: Dict[str, Dict[str, Any]] = {
    "execution": {
        "backend": "auto",            # auto, seatbelt, docker, unsafe
        "compiler": "gcc",
        "link_flags": ["-lm"],
        "compile_timeout_s": 20,
        "max_output_bytes": 1_000_000,
        "max_processes": 16,
        "docker_image": "autograder-sandbox:latest",
    },
    "first_pass": {
        "compile_flags": "-O2 -Wall -Wextra -std=c11",
        "smoke_input": None,          # None: use the first test's input
        "fail_on_smoke_crash": False,
    },
    "scoring": {
        "unavailable_policy": "renormalize",     # or "zero"
        "compile_failure_policy": "partial",     # or "zero"
        "weight_sum_policy": "error",            # or "normalize"
    },
    "report": {
        "max_text_bytes": 2000,
        "max_counterexamples": 5,
        "max_findings": 25,
        "include_usefulness_limitations": True,
    },
}

_CHOICES = {
    ("execution", "backend"): ("auto", "seatbelt", "docker", "unsafe"),
    ("scoring", "unavailable_policy"): ("renormalize", "zero"),
    ("scoring", "compile_failure_policy"): ("partial", "zero"),
    ("scoring", "weight_sum_policy"): ("error", "normalize"),
}
_TOP_LEVEL = {"problem", "time_limit_s", "memory_limit_mb", "metrics", "description",
              *DEFAULTS}
_METRIC_KEYS = {"name", "analyzer", "weight", "params", "threshold", "enabled"}


class ConfigError(ValueError):
    """The rules file is missing or invalid. The message is shown to the instructor."""


@dataclass
class Metric:
    name: str
    analyzer: str
    weight: float
    params: Dict[str, Any] = field(default_factory=dict)
    threshold: Optional[float] = None
    enabled: bool = True


@dataclass
class Rules:
    problem: str
    time_limit_s: float
    memory_limit_mb: int
    metrics: List[Metric]
    execution: Dict[str, Any]
    first_pass: Dict[str, Any]
    scoring: Dict[str, Any]
    report: Dict[str, Any]
    path: str
    hash: str
    base_dir: str

    def resolve(self, relative: str) -> str:
        """Resolve a path from the rules file against that file's directory."""
        return os.path.normpath(os.path.join(self.base_dir, relative))

    def first_testset(self) -> Optional[str]:
        """Directory of the first enabled test-set metric, shared across analyzers."""
        for metric in self.metrics:
            if metric.enabled and "testset_dir" in metric.params:
                return self.resolve(metric.params["testset_dir"])
        return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


def _merge_section(raw: Dict[str, Any], section: str, errors: List[str]) -> Dict[str, Any]:
    merged = copy.deepcopy(DEFAULTS[section])
    given = raw.get(section, {})
    if not isinstance(given, dict):
        errors.append(f"'{section}' must be an object")
        return merged
    for key, value in given.items():
        if key not in merged:
            errors.append(f"unknown setting '{section}.{key}'; "
                          f"known settings: {', '.join(sorted(merged))}")
            continue
        allowed = _CHOICES.get((section, key))
        if allowed and value not in allowed:
            errors.append(f"'{section}.{key}' must be one of {', '.join(allowed)}; "
                          f"got {value!r}")
            continue
        merged[key] = value
    return merged


def _parse_metric(raw: Any, index: int, seen: set, errors: List[str]) -> Optional[Metric]:
    label = f"metrics[{index}]"
    if not isinstance(raw, dict):
        errors.append(f"{label} must be an object")
        return None
    label = f"metric '{raw.get('name', index)}'"
    for key in sorted(set(raw) - _METRIC_KEYS):
        errors.append(f"{label}: unknown field '{key}'")
    missing = [key for key in ("name", "analyzer", "weight") if key not in raw]
    if missing:
        errors.append(f"{label}: missing {', '.join(missing)}")
        return None

    name, analyzer, weight = raw["name"], raw["analyzer"], raw["weight"]
    params = raw.get("params", {})
    threshold = raw.get("threshold")
    enabled = raw.get("enabled", True)
    valid = True
    if not isinstance(name, str) or not name:
        errors.append(f"{label}: name must be a non-empty string")
        valid = False
    elif name in seen:
        errors.append(f"{label}: duplicate metric name")
        valid = False
    else:
        seen.add(name)
    if not _is_number(weight):
        errors.append(f"{label}: weight must be a number, got {weight!r}")
        valid = False
    elif weight < 0:
        errors.append(f"{label}: weight must not be negative, got {weight}")
        valid = False
    if threshold is not None and (not _is_number(threshold) or not 0 <= threshold <= 1):
        errors.append(f"{label}: threshold must be between 0 and 1, got {threshold!r}")
        valid = False
    if not isinstance(enabled, bool):
        errors.append(f"{label}: enabled must be true or false")
        valid = False
    if not isinstance(params, dict):
        errors.append(f"{label}: params must be an object")
        return None

    analyzer_class = get_analyzer(analyzer) if isinstance(analyzer, str) else None
    if analyzer_class is None:
        errors.append(f"{label}: unknown analyzer {analyzer!r}; "
                      f"available: {', '.join(registered_analyzers())}")
        valid = False
    else:
        errors.extend(f"{label}: {problem}" for problem in analyzer_class.validate_params(params))
    if not valid:
        return None
    return Metric(name, analyzer, float(weight), params,
                  None if threshold is None else float(threshold), enabled)


def parse_rules(raw: Any, path: str, digest: str) -> Rules:
    """Validate a decoded rules document, reporting every problem at once."""
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: the top level must be a JSON object")
    errors: List[str] = []
    for key in sorted(set(raw) - _TOP_LEVEL):
        errors.append(f"unknown top-level setting '{key}'")
    for key in ("problem", "time_limit_s", "memory_limit_mb", "metrics"):
        if key not in raw:
            errors.append(f"missing required setting '{key}'")

    problem = raw.get("problem", "")
    if "problem" in raw and (not isinstance(problem, str) or not problem):
        errors.append("'problem' must be a non-empty string")
    time_limit = raw.get("time_limit_s", 1)
    if not _is_number(time_limit) or time_limit <= 0:
        errors.append(f"'time_limit_s' must be a positive number, got {time_limit!r}")
    memory_limit = raw.get("memory_limit_mb", 1)
    if isinstance(memory_limit, bool) or not isinstance(memory_limit, int) or memory_limit <= 0:
        errors.append(f"'memory_limit_mb' must be a positive integer, got {memory_limit!r}")

    sections = {name: _merge_section(raw, name, errors) for name in DEFAULTS}

    metrics: List[Metric] = []
    raw_metrics = raw.get("metrics", [])
    if not isinstance(raw_metrics, list):
        errors.append("'metrics' must be a list")
    elif "metrics" in raw and not raw_metrics:
        errors.append("'metrics' must not be empty")
    else:
        seen: set = set()
        for index, item in enumerate(raw_metrics):
            metric = _parse_metric(item, index, seen, errors)
            if metric:
                metrics.append(metric)

    enabled_total = sum(metric.weight for metric in metrics if metric.enabled)
    if metrics and not errors:
        if enabled_total <= 0:
            errors.append("at least one enabled metric must have a weight above zero")
        elif (sections["scoring"]["weight_sum_policy"] == "error"
              and abs(enabled_total - 1.0) > _WEIGHT_TOLERANCE):
            errors.append(f"enabled weights sum to {enabled_total:g}, not 1.00; fix them or "
                          "set scoring.weight_sum_policy to \"normalize\"")
    if errors:
        raise ConfigError("invalid rules in {}:\n  - {}".format(path, "\n  - ".join(errors)))
    return Rules(problem=problem, time_limit_s=float(time_limit),
                 memory_limit_mb=memory_limit, metrics=metrics, path=path, hash=digest,
                 base_dir=os.path.dirname(os.path.abspath(path)), **sections)


def load_rules(path: str) -> Rules:
    """Read a rules file. Raises :class:`ConfigError` with a usable message."""
    try:
        with open(path, "rb") as handle:
            content = handle.read()
    except OSError as error:
        raise ConfigError(f"cannot read rules file {path}: {error.strerror}") from error
    try:
        raw = json.loads(content.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise ConfigError(f"{path} is not UTF-8 text: {error}") from error
    except json.JSONDecodeError as error:
        raise ConfigError(f"{path} is not valid JSON: line {error.lineno}, "
                          f"column {error.colno}: {error.msg}") from error
    return parse_rules(raw, path, "sha256:" + hashlib.sha256(content).hexdigest())
