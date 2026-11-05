"""``llm_review``: deterministic readability score with optional LLM commentary.

The name comes from the assignment's example rules. The score here is always
computed by the deterministic checks below, so the grade is reproducible and a
model can never change it. If Ollama is available its remarks are attached as
advisory text only, and a comment in student code that tries to talk to the model
therefore cannot affect marks.

Nothing is compiled or executed. Each criterion reports evidence, and short
programs are not punished for having few comments.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from analyzers.base import AnalysisContext, Analyzer, register
from analyzers.c_source import CSource
from analyzers.llm_client import DEFAULT_BASE_URL, review_source
from models.results import AnalyzerResult

_DEFAULT_WEIGHTS = {"identifiers": 0.3, "comments": 0.2, "formatting": 0.3,
                    "function_length": 0.1, "nesting": 0.1}
_DEFAULT_ALLOWED_SHORT = ("i", "j", "k", "n", "m", "x", "y")
_STRING = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'')
_LINE_COMMENT = re.compile(r"//.*$")
_CRAMPED = re.compile(r"[\w)\]](?:[+*/%]|==|!=|<=|>=|&&|\|\||(?<![-+])=(?!=)|<|>)[\w(]")
_SHORT_PROGRAM_LINES = 15
_NEUTRAL_COMMENT_SCORE = 0.5
_MAX_LINE_LENGTH = 100


def identifier_score(source: CSource, allowed: Tuple[str, ...]) -> Tuple[float, Dict[str, Any]]:
    """Share of the program's own names that are not unexplained one-letter names."""
    defined = {function.name for function in source.functions}
    called = source.called_names()
    names = [name for name in source.identifier_counts()
             if name not in called or name in defined]
    if not names:
        return 1.0, {"names_checked": 0, "short_names": []}
    short = sorted(name for name in names if len(name) <= 2 and name not in allowed)
    return 1.0 - len(short) / len(names), {"names_checked": len(names), "short_names": short}


def comment_score(source: CSource, lines_per_comment: int) -> Tuple[float, Dict[str, Any]]:
    """Comment presence relative to size. Few comments on a short program is neutral."""
    code_lines = sum(1 for line in source.lines if line.strip())
    comments = len(source.comments)
    evidence = {"comments": comments, "non_blank_lines": code_lines}
    if comments == 0 and code_lines <= _SHORT_PROGRAM_LINES:
        return _NEUTRAL_COMMENT_SCORE, evidence
    wanted = max(code_lines / lines_per_comment, 1.0)
    return min(comments / wanted, 1.0), evidence


def _code_line(line: str) -> str:
    return _LINE_COMMENT.sub("", _STRING.sub('""', line)).rstrip()


def formatting_score(source: CSource) -> Tuple[float, Dict[str, Any]]:
    """Statements per line, operator spacing, indentation, and line length."""
    tokens_by_line: Dict[int, List[str]] = {}
    for token in source.tokens:
        tokens_by_line.setdefault(token.line, []).append(token.text)
    crowded, cramped, unindented, long_lines, checked = [], [], [], [], 0
    depth = 0
    for number, raw in enumerate(source.lines, start=1):
        texts = tokens_by_line.get(number)
        if not texts:
            continue
        checked += 1
        semicolons = texts.count(";")
        if "for" in texts:
            semicolons = max(0, semicolons - 2)
        if semicolons > 1:
            crowded.append(number)
        if _CRAMPED.search(_code_line(raw)):
            cramped.append(number)
        starting_depth = depth - 1 if texts[0] == "}" else depth
        if starting_depth > 0 and raw == raw.lstrip():
            unindented.append(number)
        depth = max(0, depth + texts.count("{") - texts.count("}"))
        if len(raw) > _MAX_LINE_LENGTH:
            long_lines.append(number)
    if checked == 0:
        return 0.0, {"lines_checked": 0}
    problems = len(set(crowded) | set(cramped) | set(unindented) | set(long_lines))
    return 1.0 - problems / checked, {
        "lines_checked": checked, "multiple_statements": crowded,
        "cramped_operators": cramped, "unindented": unindented, "long_lines": long_lines}


def _share_within(values: List[int], limit: int) -> float:
    return sum(1 for value in values if value <= limit) / len(values) if values else 1.0


@register
class ReadabilityAnalyzer(Analyzer):
    name = "llm_review"
    PARAMS = {
        "criteria_weights": (dict, False),
        "allowed_short_names": (list, False),
        "lines_per_comment": (int, False),
        "max_function_length": (int, False),
        "max_nesting": (int, False),
        "use_llm": (bool, False),
        "model": (str, False),
        "temperature": ((int, float), False),
        "seed": (int, False),
        "llm_timeout_s": ((int, float), False),
        "base_url": (str, False),
    }

    @classmethod
    def check_params(cls, params: Dict[str, Any]) -> List[str]:
        weights = params.get("criteria_weights", {})
        if not isinstance(weights, dict):
            return []
        problems = [f"unknown criterion {key!r}" for key in weights
                    if key not in _DEFAULT_WEIGHTS]
        if abs(sum(dict(_DEFAULT_WEIGHTS, **weights).values()) - 1.0) > 1e-6:
            problems.append("criteria_weights must sum to 1")
        return problems

    def run(self, context: AnalysisContext, params: Dict[str, Any]) -> AnalyzerResult:
        source = context.source
        if not source.tokens:
            return AnalyzerResult.scored(0.0, "The file contains no code.")
        allowed = tuple(params.get("allowed_short_names", _DEFAULT_ALLOWED_SHORT))
        max_length = params.get("max_function_length", 60)
        max_nesting = params.get("max_nesting", 3)
        id_score, id_evidence = identifier_score(source, allowed)
        note_score, note_evidence = comment_score(source, params.get("lines_per_comment", 25))
        format_score, format_evidence = formatting_score(source)
        lengths = [function.length for function in source.functions]
        nesting = [function.max_nesting for function in source.functions]
        criteria = {
            "identifiers": id_score,
            "comments": note_score,
            "formatting": format_score,
            "function_length": _share_within(lengths, max_length),
            "nesting": _share_within(nesting, max_nesting),
        }
        weights = dict(_DEFAULT_WEIGHTS, **params.get("criteria_weights", {}))
        score = sum(weights[key] * value for key, value in criteria.items())
        evidence: Dict[str, Any] = {
            "method": "deterministic checks; any LLM text is advisory and unscored",
            "criteria": {key: round(value, 3) for key, value in criteria.items()},
            "identifiers": id_evidence,
            "comments": note_evidence,
            "formatting": format_evidence,
            "function_lengths": lengths,
            "max_nesting_by_function": nesting,
        }
        suggestions = self._suggest(id_evidence, note_evidence, format_evidence, lengths,
                                    nesting, max_length, max_nesting, criteria)
        result = AnalyzerResult.scored(score, self._summary(criteria, id_evidence),
                                       evidence=evidence, suggestions=suggestions)
        result.evidence["llm"] = self._advisory(context, params)
        return result

    @staticmethod
    def _advisory(context: AnalysisContext, params: Dict[str, Any]) -> Dict[str, Any]:
        if not params.get("use_llm", False) or not context.allow_llm:
            return {"status": "disabled"}
        return review_source(context.source.text, params.get("model", "llama3.1"),
                             params.get("temperature", 0), params.get("seed", 42),
                             params.get("llm_timeout_s", 60),
                             params.get("base_url", DEFAULT_BASE_URL))

    @staticmethod
    def _summary(criteria: Dict[str, float], identifiers: Dict[str, Any]) -> str:
        notes = []
        if identifiers.get("short_names"):
            notes.append("terse names: " + ", ".join(identifiers["short_names"][:5]))
        if criteria["formatting"] < 0.7:
            notes.append("cramped formatting")
        if criteria["comments"] < 0.5:
            notes.append("few comments")
        return "; ".join(notes).capitalize() + "." if notes else "Reads cleanly on all criteria."

    @staticmethod
    def _suggest(identifiers: Dict[str, Any], comments: Dict[str, Any], formatting: Dict[str, Any],
                 lengths: List[int], nesting: List[int], max_length: int, max_nesting: int,
                 criteria: Dict[str, float]) -> List[str]:
        suggestions = []
        if identifiers.get("short_names"):
            suggestions.append("Use descriptive names instead of: "
                               + ", ".join(identifiers["short_names"][:8]) + ".")
        if criteria["comments"] < 1.0 and comments["comments"] == 0:
            suggestions.append("Add a short comment saying what the program does.")
        if formatting.get("multiple_statements"):
            suggestions.append("Put one statement on each line (see lines "
                               f"{formatting['multiple_statements'][:5]}).")
        if formatting.get("cramped_operators"):
            suggestions.append("Put spaces around operators (see lines "
                               f"{formatting['cramped_operators'][:5]}).")
        if formatting.get("unindented"):
            suggestions.append(f"Indent code inside braces (see lines "
                               f"{formatting['unindented'][:5]}).")
        if any(length > max_length for length in lengths):
            suggestions.append(f"Shorten functions longer than {max_length} lines.")
        if any(depth > max_nesting for depth in nesting):
            suggestions.append(f"Reduce nesting deeper than {max_nesting} levels; "
                               "early returns or helpers can help.")
        return suggestions
