"""``pattern_check``: data-driven source rules, so rules alone can add a metric.

For example, a course can ban ``gets`` or require ``fgets`` with one entry in the
rules file. Matching uses tokens, so a banned name in a comment or string is not a
false positive.
"""
from __future__ import annotations

from typing import Any, Dict, List

from analyzers.base import AnalysisContext, Analyzer, register
from models.results import AnalyzerResult


@register
class PatternCheckAnalyzer(Analyzer):
    name = "pattern_check"
    PARAMS = {
        "forbid_calls": (list, False),
        "require_calls": (list, False),
        "forbid_keywords": (list, False),
        "penalty_per_violation": ((int, float), False),
    }

    @classmethod
    def check_params(cls, params: Dict[str, Any]) -> List[str]:
        if not any(key in params for key in
                   ("forbid_calls", "require_calls", "forbid_keywords")):
            return ["at least one of forbid_calls, require_calls, forbid_keywords is needed"]
        return []

    def run(self, context: AnalysisContext, params: Dict[str, Any]) -> AnalyzerResult:
        tokens = context.source.tokens
        calls: Dict[str, int] = {}
        for index, token in enumerate(tokens[:-1]):
            if token.kind == "identifier" and tokens[index + 1].text == "(":
                calls.setdefault(token.text, token.line)
        keyword_lines = {token.text: token.line for token in reversed(tokens)}

        violations: List[Dict[str, Any]] = []
        for name in params.get("forbid_calls", []):
            if name in calls:
                violations.append({"rule": "forbidden call", "name": name, "line": calls[name]})
        for name in params.get("forbid_keywords", []):
            if name in keyword_lines:
                violations.append({"rule": "forbidden keyword", "name": name,
                                   "line": keyword_lines[name]})
        for name in params.get("require_calls", []):
            if name not in calls:
                violations.append({"rule": "required call missing", "name": name, "line": None})

        penalty = float(params.get("penalty_per_violation", 0.5))
        score = max(0.0, 1.0 - penalty * len(violations))
        evidence = {"violations": violations}
        if not violations:
            return AnalyzerResult.scored(score, "All source rules satisfied.", evidence=evidence)
        suggestions = [f"{item['rule'].capitalize()}: {item['name']}"
                       + (f" (line {item['line']})." if item["line"] else ".")
                       for item in violations]
        return AnalyzerResult.scored(score, f"{len(violations)} source rule violation(s).",
                                     evidence=evidence, suggestions=suggestions)
