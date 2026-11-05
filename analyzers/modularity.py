"""``function_split``: is the work divided into functions that are actually used?

Source-only. The three criteria are proportional, and their weights are rule
parameters so an instructor can change the balance without editing this code.
"""
from __future__ import annotations

from typing import Any, Dict, List

from analyzers.base import AnalysisContext, Analyzer, register
from models.results import AnalyzerResult

_DEFAULT_WEIGHTS = {"function_count": 0.5, "helpers_called": 0.25, "main_share": 0.25}
_DEFAULT_MAX_MAIN_SHARE = 0.7


@register
class FunctionSplitAnalyzer(Analyzer):
    name = "function_split"
    PARAMS = {
        "expect_helpers": (bool, False),
        "min_functions": (int, False),
        "max_main_share": ((int, float), False),
        "criteria_weights": (dict, False),
    }

    @classmethod
    def check_params(cls, params: Dict[str, Any]) -> List[str]:
        weights = params.get("criteria_weights", {})
        if not isinstance(weights, dict):
            return []
        problems = [f"unknown criterion {key!r}" for key in weights
                    if key not in _DEFAULT_WEIGHTS]
        merged = dict(_DEFAULT_WEIGHTS, **weights)
        if abs(sum(merged.values()) - 1.0) > 1e-6:
            problems.append("criteria_weights must sum to 1")
        return problems

    def run(self, context: AnalysisContext, params: Dict[str, Any]) -> AnalyzerResult:
        source = context.source
        functions = source.functions
        if not functions:
            return AnalyzerResult.scored(0.0, "No function definitions were found.",
                                         evidence={"functions_defined": 0})

        names = [item.name for item in functions]
        helpers = [name for name in names if name != "main"]
        expect_helpers = params.get("expect_helpers", True)
        min_functions = params.get("min_functions", 2) if expect_helpers else 1
        reachable = self._reachable(context)
        used = [name for name in helpers if name in reachable]
        unused = [name for name in helpers if name not in reachable]

        total_lines = sum(item.length for item in functions)
        main = source.function("main")
        main_share = (main.length / total_lines) if main else 0.0
        max_share = params.get("max_main_share", _DEFAULT_MAX_MAIN_SHARE)

        weights = dict(_DEFAULT_WEIGHTS, **params.get("criteria_weights", {}))
        criteria = {
            "function_count": min(len(functions) / max(min_functions, 1), 1.0),
            "helpers_called": (len(used) / len(helpers)) if helpers else
                              (0.0 if expect_helpers else 1.0),
            "main_share": 1.0 if main_share <= max_share or not expect_helpers else
                          max(0.0, (1.0 - main_share) / (1.0 - max_share)),
        }
        score = sum(weights[key] * value for key, value in criteria.items())
        evidence = {
            "functions_defined": len(functions),
            "expected_min": min_functions,
            "names": names,
            "helpers_reachable_from_main": used,
            "helpers_unused": unused,
            "main_share_of_function_lines": round(main_share, 3),
            "criteria": {key: round(value, 3) for key, value in criteria.items()},
        }
        suggestions = []
        if len(functions) < min_functions:
            suggestions.append(f"Only {len(functions)} function(s) defined; at least "
                               f"{min_functions} expected. Extract a helper from main().")
        if unused:
            suggestions.append(f"Helper(s) never called from main(): {', '.join(unused)}.")
        if expect_helpers and helpers and main_share > max_share:
            suggestions.append(f"main() holds {main_share:.0%} of the function lines. "
                               "Move more logic into helpers.")
        feedback = (f"Only {names[0]}() is defined." if len(names) == 1
                    else f"{len(functions)} functions, {len(used)} helper(s) in use.")
        return AnalyzerResult.scored(score, feedback, evidence=evidence,
                                     suggestions=suggestions)

    @staticmethod
    def _reachable(context: AnalysisContext) -> set:
        """Names reachable through calls from main. A helper only recursing is unused."""
        source = context.source
        seen: set = set()
        pending = ["main"]
        while pending:
            function = source.function(pending.pop())
            if function is None or function.name in seen:
                continue
            seen.add(function.name)
            pending.extend(function.calls)
        return seen
