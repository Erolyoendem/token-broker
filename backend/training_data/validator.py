"""
Code validator – syntactic correctness + semantic plausibility checks.

Combines language-pair-specific validation with general heuristics
to produce a confidence score for each generated code pair.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .language_pairs import LanguagePair, ValidationResult

log = logging.getLogger(__name__)

# Minimum confidence to accept a pair without human review
ACCEPT_THRESHOLD = 0.70


@dataclass
class PairScore:
    syntax_ok: bool
    warnings: list[str]
    heuristic_score: float          # 0.0 – 1.0
    confidence: float               # 0.0 – 1.0 composite
    requires_review: bool = False
    notes: list[str] = field(default_factory=list)


class Validator:
    """Validates a (source, target) code pair for a given LanguagePair."""

    def validate_pair(
        self,
        source_code: str,
        target_code: str,
        pair: LanguagePair,
    ) -> PairScore:
        # 1. Reject empty output immediately
        if not target_code.strip():
            return PairScore(
                syntax_ok=False,
                warnings=["target code is empty"],
                heuristic_score=0.0,
                confidence=0.0,
                requires_review=True,
                notes=["empty conversion output"],
            )

        # 2. Language-specific validation (syntax etc.)
        lang_result: ValidationResult = pair.validate(target_code)

        # 2. General heuristics
        heuristic_score = self._heuristic_score(source_code, target_code, pair)

        # 3. Composite confidence
        syntax_pts = 1.0 if lang_result.ok else 0.0
        confidence = round(syntax_pts * 0.6 + heuristic_score * 0.4, 3)

        return PairScore(
            syntax_ok=lang_result.ok,
            warnings=lang_result.warnings,
            heuristic_score=round(heuristic_score, 3),
            confidence=confidence,
            requires_review=confidence < ACCEPT_THRESHOLD,
            notes=lang_result.errors,
        )

    # ── Heuristics ────────────────────────────────────────────────────────────

    def _heuristic_score(
        self, source: str, target: str, pair: LanguagePair
    ) -> float:
        scores: list[float] = []

        # Non-empty output
        scores.append(1.0 if target.strip() else 0.0)

        # Length ratio (target should be roughly same length as source)
        if source.strip():
            ratio = len(target) / max(len(source), 1)
            # Accept 0.3x – 3x length
            scores.append(min(1.0, 1.0 - abs(1.0 - ratio) * 0.3))

        # Structural complexity preserved: count functions/classes in source
        src_defs = len(re.findall(r"\bdef\b|\bclass\b|\bfunction\b|\bfn\b", source))
        tgt_defs = len(re.findall(r"\bdef\b|\bclass\b|\bfunction\b|\bfn\b", target))
        if src_defs > 0:
            def_ratio = min(tgt_defs, src_defs) / src_defs
            scores.append(def_ratio)
        else:
            scores.append(1.0)

        # No leftover source-language keywords (simple check)
        if pair.source_lang == "ruby":
            leakage = len(re.findall(r"\bputs\b|\brequire\b|\bend\b", target))
            scores.append(max(0.0, 1.0 - leakage * 0.2))
        elif pair.source_lang == "javascript" and pair.target_lang == "typescript":
            # TypeScript should have type annotations
            has_types = bool(re.search(r":\s*(string|number|boolean|void|unknown)", target))
            scores.append(1.0 if has_types else 0.5)
        else:
            scores.append(1.0)

        return sum(scores) / len(scores) if scores else 0.0
