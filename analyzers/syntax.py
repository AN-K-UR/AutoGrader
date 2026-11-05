"""``compiler_warnings``: compile status and warnings under the rule's flags."""
from __future__ import annotations

from typing import Any, Dict, List

from analyzers.base import AnalysisContext, Analyzer, register
from execution.compiler import compile_source, split_flags
from models.results import AnalyzerResult, Diagnostic, to_plain


@register
class CompilerWarningsAnalyzer(Analyzer):
    name = "compiler_warnings"
    PARAMS = {
        "flags": ((str, list), False),
        "penalty_per_warning": ((int, float), False),
    }

    def run(self, context: AnalysisContext, params: Dict[str, Any]) -> AnalyzerResult:
        if not context.first_pass.compiled:
            errors = [item for item in context.compile_result.diagnostics
                      if item.severity == "error"]
            return AnalyzerResult.scored(
                0.0, "The program does not compile.",
                evidence={"errors": to_plain(errors),
                          "compiler_output": context.compile_result.output})

        execution = context.rules.execution
        flags = split_flags(params.get("flags", "-Wall -Wextra -std=c11"))
        checked = compile_source(context.backend, execution["compiler"],
                                 [context.source_file], None, flags, context.workdir,
                                 execution["compile_timeout_s"])
        # With -Werror a warning arrives as an error tagged with its -W flag.
        warnings: List[Diagnostic] = [item for item in checked.diagnostics
                                      if item.severity == "warning"
                                      or (item.code or "").startswith("-W")]
        penalty = float(params.get("penalty_per_warning", 0.1))
        score = max(0.0, 1.0 - penalty * len(warnings))
        evidence = {"flags": flags, "warnings": to_plain(warnings)}
        if not warnings:
            return AnalyzerResult.scored(score, "No compiler warnings.", evidence=evidence)
        codes = sorted({item.code or "warning" for item in warnings})
        suggestions = [f"Line {item.line}: {item.message}" for item in warnings[:5]]
        return AnalyzerResult.scored(score, f"{len(warnings)} warning(s): {', '.join(codes)}",
                                     evidence=evidence, suggestions=suggestions)
