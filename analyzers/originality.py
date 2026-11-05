"""``similarity_flag``: token-based comparison against a local corpus.

Method: tokenise with comments removed, replace identifiers, numbers and strings
with placeholders (library calls stay, since they carry meaning), then compare
sets of 5-token shingles with Jaccard similarity. Using shingles rather than
single tokens is what stops shared keywords from counting as similarity, and
placeholders make renaming useless.

A high score is a reason for a human to look, never proof of copying. Direct
comparison against the live internet or against LLM output is not possible: the
"online" and "llm" evidence comes only from what the instructor put in the corpus.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from analyzers.base import AnalysisContext, Analyzer, register
from analyzers.c_source import C_KEYWORDS, CSource
from models.results import AnalyzerResult

SHINGLE_SIZE = 5
_LIBRARY_NAMES = frozenset("""
printf scanf puts putchar getchar gets fgets fopen fclose fprintf fscanf sprintf sscanf
malloc calloc realloc free memcpy memset memmove strlen strcpy strncpy strcmp strncmp
strcat strchr strstr qsort bsearch atoi atol strtol abs labs exit rand srand sqrt pow
""".split())
_CORPUS_KINDS = ("peers", "online", "llm")
_DEFAULT_FLAGGED_SCORE = 0.5
_SIGNAL_THRESHOLD = 3
# Weak hints only. Plenty of careful students write this way, so these are shown
# to the instructor as context and never touch the score or raise a copying flag.
_STYLE_SIGNALS = {
    "narrated step comments": re.compile(r"\bstep\s*\d+\b", re.IGNORECASE),
    "complexity commentary": re.compile(r"\b(time|space) complexity\b", re.IGNORECASE),
    "function-narration comments": re.compile(r"\bthis (function|program) (will )?\w+s?\b",
                                              re.IGNORECASE),
    "edge-case commentary": re.compile(r"\bedge cases?\b", re.IGNORECASE),
    "example-usage commentary": re.compile(r"\bexample usage\b", re.IGNORECASE),
    "input-validation narration": re.compile(r"\b(validate|check) (the )?(user )?input\b",
                                             re.IGNORECASE),
}


def normalize_tokens(source: CSource) -> List[str]:
    """Reduce source to a stream that ignores names, literals, layout and comments."""
    normalized = []
    for token in source.tokens:
        if token.kind == "identifier":
            keep = token.text in C_KEYWORDS or token.text in _LIBRARY_NAMES
            normalized.append(token.text if keep else "ID")
        elif token.kind == "number":
            normalized.append("NUM")
        elif token.kind in ("string", "char"):
            normalized.append("STR")
        else:
            normalized.append(token.text)
    return normalized


def shingles(tokens: List[str], size: int = SHINGLE_SIZE) -> Set[Tuple[str, ...]]:
    if len(tokens) < size:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[index:index + size]) for index in range(len(tokens) - size + 1)}


def jaccard(left: Set[Any], right: Set[Any]) -> float:
    if not left and not right:
        return 0.0
    return len(left & right) / len(left | right)


def containment(part: Set[Any], whole: Set[Any]) -> float:
    """How much of ``part`` appears in ``whole``. Catches a copy with code added."""
    return len(part & whole) / len(part) if part else 0.0


def style_signals(source: CSource) -> List[str]:
    text = "\n".join(comment.text for comment in source.comments)
    return sorted(name for name, pattern in _STYLE_SIGNALS.items() if pattern.search(text))


def _kind_of(relative_path: str) -> str:
    first = relative_path.replace(os.sep, "/").split("/", 1)[0]
    return first if first in _CORPUS_KINDS else "peers"


def _read_corpus(directory: str, submission: str) -> List[Tuple[str, str]]:
    """Corpus files in stable order, excluding the submission itself by path."""
    own_path = os.path.realpath(submission) if submission else ""
    entries = []
    for root, folders, files in os.walk(directory):
        folders.sort()
        for name in sorted(files):
            path = os.path.join(root, name)
            if name.endswith(".c") and os.path.realpath(path) != own_path:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    entries.append((os.path.relpath(path, directory), handle.read()))
    return entries


def _fingerprint(text: str, template: Set[Tuple[str, ...]]) -> Set[Tuple[str, ...]]:
    return shingles(normalize_tokens(CSource(text))) - template


@register
class SimilarityAnalyzer(Analyzer):
    name = "similarity_flag"
    PARAMS = {
        "corpus_dir": (str, True),
        "flag_threshold": ((int, float), False),
        "containment_threshold": ((int, float), False),
        "template_file": (str, False),
        "flagged_score": ((int, float), False),
        "top_matches": (int, False),
    }

    @classmethod
    def check_params(cls, params: Dict[str, Any]) -> List[str]:
        problems = []
        for key in ("flag_threshold", "containment_threshold", "flagged_score"):
            value = params.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) \
                    and not 0 <= value <= 1:
                problems.append(f"{key} must be between 0 and 1, got {value}")
        return problems

    def run(self, context: AnalysisContext, params: Dict[str, Any]) -> AnalyzerResult:
        directory = context.rules.resolve(params["corpus_dir"])
        if not os.path.isdir(directory):
            return AnalyzerResult.not_evaluated("no comparison corpus: "
                                                f"{os.path.basename(directory.rstrip('/'))} "
                                                "does not exist")
        corpus = _read_corpus(directory, context.original_path)
        if not corpus:
            return AnalyzerResult.not_evaluated("the comparison corpus has no C files")

        template = self._template(context, params.get("template_file"))
        mine = shingles(normalize_tokens(context.source)) - template
        matches = []
        for path, text in corpus:
            theirs = _fingerprint(text, template)
            matches.append({
                "target": path,
                "kind": _kind_of(path),
                "jaccard": round(jaccard(mine, theirs), 4),
                "containment": round(containment(mine, theirs), 4),
            })
        matches.sort(key=lambda item: (-item["jaccard"], -item["containment"], item["target"]))

        threshold = float(params.get("flag_threshold", 0.85))
        containment_limit = float(params.get("containment_threshold", 0.95))
        flagged = [item for item in matches
                   if item["jaccard"] >= threshold or item["containment"] >= containment_limit]
        top = matches[0]
        signals = style_signals(context.source)
        evidence: Dict[str, Any] = {
            "metric": f"Jaccard over {SHINGLE_SIZE}-token shingles of normalized tokens",
            "comparisons": len(corpus),
            "max_similarity": top["jaccard"],
            "closest": top["target"],
            "threshold": threshold,
            "containment_threshold": containment_limit,
            "submission_shingles": len(mine),
            "top_matches": matches[:params.get("top_matches", 3)],
            "style_signals_advisory": signals,
            "limitations": "Similarity is grounds for review, not proof. It cannot see "
                           "sources outside the corpus and cannot identify LLM authorship.",
        }
        if len(mine) < 2 * SHINGLE_SIZE:
            evidence["low_confidence"] = "very short program; high similarity is expected"

        flags: List[Dict[str, Any]] = []
        if len(signals) >= _SIGNAL_THRESHOLD:
            flags.append({"type": "style_signals_advisory", "signals": signals,
                          "note": "Weak hint for context only; unscored and not evidence "
                                  "of LLM use."})
        if not flagged:
            return AnalyzerResult.scored(
                1.0, f"Max similarity {top['jaccard']:.2f} against {len(corpus)} file(s); "
                     "not flagged.", evidence=evidence, flags=flags)

        for item in flagged:
            flags.append({"type": "suspected_copying", "source_kind": item["kind"],
                          "target": item["target"], "similarity": item["jaccard"],
                          "containment": item["containment"],
                          "note": "Flag for human review; similarity does not prove copying."})
        return AnalyzerResult.scored(
            float(params.get("flagged_score", _DEFAULT_FLAGGED_SCORE)),
            f"Flagged for review: similarity {flagged[0]['jaccard']:.2f} with "
            f"{flagged[0]['target']} ({flagged[0]['kind']}), threshold {threshold:.2f}.",
            evidence=evidence, flags=flags,
            suggestions=["This submission closely matches another source and an instructor "
                         "will review it. If you used a source, cite it."])

    @staticmethod
    def _template(context: AnalysisContext, path: Optional[str]) -> Set[Tuple[str, ...]]:
        """Shingles of instructor-supplied starter code, which everyone shares."""
        if not path:
            return set()
        resolved = context.rules.resolve(path)
        if not os.path.isfile(resolved):
            return set()
        with open(resolved, encoding="utf-8", errors="replace") as handle:
            return shingles(normalize_tokens(CSource(handle.read())))
