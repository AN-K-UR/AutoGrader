"""The analyzer contract, the registry, and the context analyzers receive.

Dropping a new module into ``analyzers/`` that applies :func:`register` is all it
takes for rules to name a new analyzer: modules here are discovered at runtime,
so the agent itself is never edited.
"""
from __future__ import annotations

import importlib
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Type

from models.results import AnalyzerResult, CompileResult, FirstPass

if TYPE_CHECKING:
    from agent.config_loader import Rules
    from analyzers.c_source import CSource
    from execution.sandbox import ExecutionBackend

_REGISTRY: Dict[str, Type["Analyzer"]] = {}
_discovered = False


@dataclass
class AnalysisContext:
    """Everything an analyzer may look at for one submission."""

    source_name: str          # file name as submitted, for display only
    source_file: str          # path relative to workdir of the private copy
    source: "CSource"
    rules: "Rules"
    backend: "ExecutionBackend"
    workdir: str
    compile_result: CompileResult
    first_pass: FirstPass
    binary: Optional[str] = None
    original_path: str = ""
    allow_llm: bool = True
    shared: Dict[str, Any] = field(default_factory=dict)


class Analyzer(ABC):
    """One metric's evaluator.

    ``needs_execution`` analyzers run the program, so they are skipped when the
    program cannot run and are never run concurrently: parallel load could push
    a borderline program over its time limit and change the grade.
    """

    name = ""
    needs_execution = False
    # param -> (expected type or tuple of types, required?)
    PARAMS: Dict[str, Tuple[Any, bool]] = {}

    @abstractmethod
    def run(self, context: AnalysisContext, params: Dict[str, Any]) -> AnalyzerResult:
        """Evaluate the submission. Must not raise for submission-caused problems."""

    @classmethod
    def validate_params(cls, params: Dict[str, Any]) -> List[str]:
        """Return human-readable problems with ``params``."""
        problems = []
        for key, value in params.items():
            if key not in cls.PARAMS:
                known = ", ".join(sorted(cls.PARAMS)) or "none"
                problems.append(f"unknown param '{key}' for analyzer {cls.name} "
                                f"(known: {known})")
                continue
            expected = cls.PARAMS[key][0]
            if not isinstance(value, expected) or (isinstance(value, bool)
                                                   and expected is not bool
                                                   and bool not in _as_tuple(expected)):
                problems.append(f"param '{key}' has the wrong type: {value!r}")
        for key, (_, required) in cls.PARAMS.items():
            if required and key not in params:
                problems.append(f"param '{key}' is required by analyzer {cls.name}")
        problems.extend(cls.check_params(params))
        return problems

    @classmethod
    def check_params(cls, params: Dict[str, Any]) -> List[str]:
        """Hook for analyzer-specific value checks."""
        return []


def _as_tuple(value: Any) -> Tuple[Any, ...]:
    return value if isinstance(value, tuple) else (value,)


def register(cls: Type[Analyzer]) -> Type[Analyzer]:
    if not cls.name:
        raise ValueError(f"{cls.__name__} has no analyzer name")
    _REGISTRY[cls.name] = cls
    return cls


def _discover() -> None:
    global _discovered
    if _discovered:
        return
    _discovered = True
    import analyzers
    for module in pkgutil.iter_modules(analyzers.__path__):
        importlib.import_module(f"analyzers.{module.name}")


def get_analyzer(name: str) -> Optional[Type[Analyzer]]:
    _discover()
    return _REGISTRY.get(name)


def registered_analyzers() -> List[str]:
    _discover()
    return sorted(_REGISTRY)
