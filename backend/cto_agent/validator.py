"""
Validator & RuleEngine – Validates agent proposals against stored rules.

Rules are extracted programmatically from tasks/lessons.md using the pattern:

  RULE: <condition> → <action>

Examples from lessons.md:
  RULE: token_cost_increase > 20% → reject
  RULE: success_rate < 70% → alert
  RULE: provider == "unknown" → reject

The RuleEngine also applies hard constraints from ProjectConfig.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Decision:
    approved: bool
    rationale: str
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "rationale": self.rationale,
            "violations": self.violations,
        }


@dataclass
class Rule:
    raw: str
    condition_text: str
    action: str          # "reject" | "alert" | "warn" | "accept"

    def applies_to(self, proposal: str, context: dict[str, Any]) -> bool:
        """
        Evaluate whether this rule's condition is triggered.
        Numeric conditions are checked against context values; if the
        relevant context key is present, keyword fallback is skipped.
        """
        cond = self.condition_text.lower()

        # Numeric comparisons: check value, return result immediately (no keyword fallback)
        if "token_cost_increase" in cond:
            pct = context.get("token_cost_increase_pct", 0.0)
            m = re.search(r">\s*([\d.]+)%", cond)
            if m:
                return pct > float(m.group(1))

        if "success_rate" in cond:
            rate = context.get("success_rate", 1.0)
            m = re.search(r"<\s*([\d.]+)%", cond)
            if m:
                return rate < float(m.group(1)) / 100

        # Provider equality check
        if "provider" in cond:
            provider = context.get("provider", "")
            m = re.search(r'==\s*["\']?(\w+)["\']?', cond)
            if m:
                return provider.lower() == m.group(1).lower()

        # Generic keyword fallback: only if no structured check matched
        text = (proposal + " " + str(context)).lower()
        keywords = re.findall(r"\b[a-z_]{6,}\b", cond)  # 6+ chars to reduce false positives
        return bool(keywords) and any(kw in text for kw in keywords)


class RuleEngine:
    """
    Extracts RULE: lines from a Markdown document and evaluates them
    against a proposal + context dict.
    """

    _RULE_RE = re.compile(
        r"^RULE:\s*(.+?)\s*→\s*(\w+)\s*$", re.I | re.M
    )

    def __init__(self, lessons_text: str = "") -> None:
        self.rules: list[Rule] = self._parse(lessons_text)

    def _parse(self, text: str) -> list[Rule]:
        rules = []
        for m in self._RULE_RE.finditer(text):
            condition = m.group(1).strip()
            action = m.group(2).strip().lower()
            rules.append(Rule(raw=m.group(0), condition_text=condition, action=action))
        return rules

    def evaluate(self, proposal: str, context: dict[str, Any]) -> list[str]:
        """Return list of violation messages (empty = all clear)."""
        violations = []
        for rule in self.rules:
            if rule.action in ("reject", "block") and rule.applies_to(proposal, context):
                violations.append(
                    f"Rule violation [{rule.action.upper()}]: "
                    f"{rule.condition_text} (rule: {rule.raw!r})"
                )
        return violations


class Validator:
    """
    Combines RuleEngine (lessons.md) with hard ProjectConfig constraints.
    """

    def __init__(self, config: Any, lessons_text: str = "") -> None:
        self.config = config
        self.engine = RuleEngine(lessons_text)

    def check_proposal(
        self, proposal: str, context: dict[str, Any]
    ) -> list[str]:
        """
        Returns list of violation strings. Empty list → approved.

        Context keys used:
          token_cost_increase_pct : float  – e.g. 25.0 for 25%
          success_rate            : float  – 0.0–1.0
          provider                : str
        """
        violations: list[str] = []

        # 1. Hard config constraints
        pct = context.get("token_cost_increase_pct", 0.0)
        if pct > self.config.token_cost_increase_limit * 100:
            violations.append(
                f"Token cost increase {pct:.1f}% exceeds limit "
                f"{self.config.token_cost_increase_limit * 100:.0f}%"
            )

        rate = context.get("success_rate", 1.0)
        if rate < self.config.min_success_rate:
            violations.append(
                f"Agent success rate {rate:.0%} below minimum "
                f"{self.config.min_success_rate:.0%}"
            )

        provider = context.get("provider", "")
        if provider and provider not in self.config.preferred_providers + [""]:
            violations.append(
                f"Provider '{provider}' not in preferred list "
                f"{self.config.preferred_providers}"
            )

        # 2. Architecture constraints from config
        for constraint in self.config.architecture_constraints:
            kw = constraint.lower()
            if kw in proposal.lower():
                violations.append(
                    f"Architecture constraint violated: {constraint!r}"
                )

        # 3. Rule-engine (from lessons.md)
        violations.extend(self.engine.evaluate(proposal, context))
        return violations
