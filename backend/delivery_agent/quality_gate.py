"""
QualityGate – Validiert Ergebnisse nach jeder Migrations-Phase.

Prüft:
  1. Token-Budget nicht überschritten
  2. Mindest-Score der Konvertierung erreicht
  3. Keine kritischen Fehler in den Logs
  4. Ausführungsphase hat mindestens einen Schritt abgeschlossen

Bei Fehlschlag gibt QualityResult.passed=False zurück und nennt den Grund.
Die DeliveryOrchestrator-Schicht entscheidet dann über Rollback oder Retry.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .orchestrator import DeliveryJob

log = logging.getLogger(__name__)

# Schwellwerte
MIN_SCORE:         float = 0.5    # Mindest-Konvertierungs-Score
MAX_TOKEN_BUDGET:  int   = 500_000  # Token-Limit pro Job
ERROR_KEYWORDS:    list  = ["traceback", "exception", "fatal", "out of memory"]


@dataclass
class QualityResult:
    passed:   bool
    reason:   str   = ""
    checks:   dict  = field(default_factory=dict)
    score:    float = 0.0

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "checks": self.checks,
            "score":  self.score,
        }


class QualityGate:
    """
    Validiert einen abgeschlossenen Job anhand mehrerer Kriterien.

    Alle Checks müssen bestehen. Bei erstem Fehler wird abgebrochen
    und der Grund zurückgegeben.
    """

    def __init__(
        self,
        min_score: float = MIN_SCORE,
        max_tokens: int  = MAX_TOKEN_BUDGET,
    ) -> None:
        self.min_score  = min_score
        self.max_tokens = max_tokens

    def validate(self, job: "DeliveryJob") -> QualityResult:
        checks: dict[str, bool] = {}

        # Check 1: Execution completed at least one step
        exec_result = job.plan.get("execution_result", {})
        steps_ok = exec_result.get("steps_completed", 0) > 0 and exec_result.get("ok", False)
        checks["execution_completed"] = steps_ok
        if not steps_ok:
            return QualityResult(
                passed=False,
                reason="Execution phase did not complete any steps.",
                checks=checks,
            )

        # Check 2: No critical errors in logs
        combined_logs = " ".join(job.logs).lower()
        no_errors = not any(kw in combined_logs for kw in ERROR_KEYWORDS)
        checks["no_critical_errors"] = no_errors
        if not no_errors:
            matched = [kw for kw in ERROR_KEYWORDS if kw in combined_logs]
            return QualityResult(
                passed=False,
                reason=f"Critical error keywords found in logs: {matched}",
                checks=checks,
            )

        # Check 3: Score threshold (from assessment or conversion result)
        score = float(job.plan.get("execution_result", {}).get("score", 1.0))
        checks["score_threshold"] = score >= self.min_score
        if score < self.min_score:
            return QualityResult(
                passed=False,
                reason=f"Score {score:.2f} below threshold {self.min_score}.",
                checks=checks,
                score=score,
            )

        # Check 4: Token budget
        tokens_used = job.plan.get("execution_result", {}).get("tokens_used", 0)
        within_budget = tokens_used <= self.max_tokens
        checks["within_token_budget"] = within_budget
        if not within_budget:
            return QualityResult(
                passed=False,
                reason=f"Token budget exceeded: {tokens_used} > {self.max_tokens}.",
                checks=checks,
                score=score,
            )

        log.info("[QualityGate] Job %s passed all checks.", job.id[:8])
        return QualityResult(passed=True, checks=checks, score=score)
