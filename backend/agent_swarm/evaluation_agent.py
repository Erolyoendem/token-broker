"""
EvaluationAgent – Scores generated Python code without executing it.

Scoring dimensions (each 0–1, equal weight):
  syntax     – AST parse succeeds
  structure  – has same number of class/function definitions as Ruby input
  length     – output length is reasonable (not empty, not suspiciously short)
  idioms     – uses Python built-ins instead of Ruby-isms (no `puts`, no `end`)

Final score = mean of all dimensions, clipped to [0.0, 1.0].
Score ≥ 0.5 is considered a "successful" conversion.
"""
from __future__ import annotations

import ast
import re
import time
from typing import Any

from .base_agent import BaseAgent


def _count_ruby_defs(ruby_code: str) -> tuple[int, int]:
    """Return (class_count, method_count) for Ruby source."""
    classes = len(re.findall(r"^\s*class\s+\w", ruby_code, re.MULTILINE))
    methods = len(re.findall(r"^\s*def\s+\w", ruby_code, re.MULTILINE))
    return classes, methods


def _count_python_defs(python_code: str) -> tuple[int, int]:
    try:
        tree = ast.parse(python_code)
    except SyntaxError:
        return 0, 0
    classes = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    functions = sum(
        1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    return classes, functions


def evaluate_code(ruby_code: str, python_code: str) -> dict[str, Any]:
    """Return scores dict and final composite score."""
    scores: dict[str, float] = {}

    # 1. Syntax check
    try:
        ast.parse(python_code)
        scores["syntax"] = 1.0
    except SyntaxError as exc:
        scores["syntax"] = 0.0
        return {
            "scores": scores,
            "score": 0.0,
            "feedback": f"SyntaxError: {exc}",
        }

    # 2. Structural similarity
    r_cls, r_meth = _count_ruby_defs(ruby_code)
    p_cls, p_fn = _count_python_defs(python_code)
    total_expected = r_cls + r_meth
    total_actual = p_cls + p_fn
    if total_expected == 0:
        scores["structure"] = 1.0
    else:
        # allow ±1 difference without penalty
        diff = abs(total_expected - total_actual)
        scores["structure"] = max(0.0, 1.0 - (diff - 1) / total_expected) if diff > 1 else 1.0

    # 3. Length sanity (output should be at least 20% of input length, not absurdly small)
    ratio = len(python_code) / max(len(ruby_code), 1)
    if ratio < 0.2:
        scores["length"] = 0.3
    elif ratio > 10:
        scores["length"] = 0.5  # suspiciously long
    else:
        scores["length"] = 1.0

    # 4. No Ruby-isms in output
    ruby_isms = re.findall(r"\bputs\b|\bend\b|\battr_accessor\b|\bdo\s*\|", python_code)
    scores["idioms"] = max(0.0, 1.0 - len(ruby_isms) * 0.25)

    final_score = round(sum(scores.values()) / len(scores), 3)
    feedback_parts = []
    if scores["structure"] < 1.0:
        feedback_parts.append(
            f"structure mismatch: Ruby {r_cls}cls/{r_meth}def vs Python {p_cls}cls/{p_fn}fn"
        )
    if ruby_isms:
        feedback_parts.append(f"Ruby-isms found: {ruby_isms}")
    if scores["length"] < 1.0:
        feedback_parts.append(f"length ratio {ratio:.2f}")

    return {
        "scores": scores,
        "score": final_score,
        "feedback": "; ".join(feedback_parts) if feedback_parts else "OK",
    }


class EvaluationAgent(BaseAgent):
    """Synchronous evaluation agent (no network calls needed)."""

    async def run(self, task: dict[str, Any]) -> dict[str, Any]:
        """
        task: {"filename": str, "ruby_code": str, "python_code": str}
        returns: {"ok": bool, "score": float, "scores": dict, "feedback": str}
        """
        t0 = time.perf_counter()
        ruby_code = task.get("ruby_code", "")
        python_code = task.get("python_code", "")

        if not python_code:
            self._record(success=False, tokens=0, elapsed=0.0)
            return {"ok": False, "score": 0.0, "scores": {}, "feedback": "empty output"}

        result = evaluate_code(ruby_code, python_code)
        elapsed = round(time.perf_counter() - t0, 4)
        success = result["score"] >= 0.5
        self._record(success=success, tokens=0, elapsed=elapsed)

        return {
            "ok": success,
            "score": result["score"],
            "scores": result["scores"],
            "feedback": result["feedback"],
            "elapsed_s": elapsed,
        }
