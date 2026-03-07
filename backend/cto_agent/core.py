"""
CTOAgent – Central architecture oversight and decision authority.

Loads project context from:
  - project_config.yaml  (machine-readable settings and constraints)
  - PROJECT_CONTEXT.md   (architecture narrative, optional)
  - tasks/lessons.md     (accumulated rules and learnings)
  - NEXT_SESSION.md      (open tasks and deployment state)

All other CTO-agent modules obtain their shared context through this class.
"""
from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class ProjectConfig:
    """Typed view of project_config.yaml (or sensible defaults)."""
    token_cost_increase_limit: float = 0.20   # reject if cost rises >20%
    min_success_rate: float = 0.70            # reject agents below this rate
    max_batch_size: int = 50
    preferred_providers: list[str] = field(default_factory=lambda: ["nvidia", "deepseek"])
    architecture_constraints: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "ProjectConfig":
        if not path.exists():
            return cls()
        try:
            raw = yaml.safe_load(path.read_text()) or {}
        except Exception:
            return cls()
        return cls(
            token_cost_increase_limit=raw.get("token_cost_increase_limit", 0.20),
            min_success_rate=raw.get("min_success_rate", 0.70),
            max_batch_size=raw.get("max_batch_size", 50),
            preferred_providers=raw.get("preferred_providers", ["nvidia", "deepseek"]),
            architecture_constraints=raw.get("architecture_constraints", []),
            extra=raw,
        )


class CTOAgent:
    """
    Central decision-making agent for architecture oversight.

    Usage::

        cto = CTOAgent()
        decision = cto.decide("Should we add Redis caching?", context={...})
        print(decision.approved, decision.rationale)
    """

    def __init__(self, repo_root: Path = _REPO_ROOT) -> None:
        self.root = repo_root
        self.config = ProjectConfig.load(repo_root / "project_config.yaml")
        self.context_md = self._read_optional(repo_root / "PROJECT_CONTEXT.md")
        self.lessons_md = self._read_optional(repo_root / "tasks" / "lessons.md")
        self.next_session_md = self._read_optional(repo_root / "NEXT_SESSION.md")

        # Lazy-loaded sub-components (avoid circular imports)
        self._validator: Optional["Validator"] = None  # noqa: F821
        self._lessons_mgr: Optional["LessonsManager"] = None  # noqa: F821

    # ── Context access ────────────────────────────────────────────────────────

    def reload(self) -> None:
        """Re-read all context files (call after external writes)."""
        self.config = ProjectConfig.load(self.root / "project_config.yaml")
        self.context_md = self._read_optional(self.root / "PROJECT_CONTEXT.md")
        self.lessons_md = self._read_optional(self.root / "tasks" / "lessons.md")
        self.next_session_md = self._read_optional(self.root / "NEXT_SESSION.md")
        self._validator = None  # reset cached validator

    @property
    def validator(self) -> "Validator":
        from .validator import Validator
        if self._validator is None:
            self._validator = Validator(self.config, self.lessons_md)
        return self._validator

    @property
    def lessons(self) -> "LessonsManager":
        from .lessons import LessonsManager
        if self._lessons_mgr is None:
            self._lessons_mgr = LessonsManager(self.root / "tasks" / "lessons.md")
        return self._lessons_mgr

    # ── High-level decision API ───────────────────────────────────────────────

    def decide(self, proposal: str, context: dict[str, Any] | None = None) -> "Decision":
        """
        Validate a free-text proposal against current rules and config.
        Returns a Decision with approved flag and rationale.
        """
        from .validator import Decision
        context = context or {}
        violations = self.validator.check_proposal(proposal, context)
        approved = len(violations) == 0
        rationale = (
            "Proposal approved – no rule violations detected."
            if approved
            else "Rejected: " + "; ".join(violations)
        )
        return Decision(approved=approved, rationale=rationale, violations=violations)

    def summary(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot of CTO agent state."""
        from .validator import RuleEngine
        engine = RuleEngine(self.lessons_md)
        return {
            "config": {
                "token_cost_increase_limit": self.config.token_cost_increase_limit,
                "min_success_rate": self.config.min_success_rate,
                "max_batch_size": self.config.max_batch_size,
                "preferred_providers": self.config.preferred_providers,
            },
            "active_rules": len(engine.rules),
            "architecture_constraints": self.config.architecture_constraints,
            "lessons_loaded": bool(self.lessons_md),
            "context_loaded": bool(self.context_md),
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _read_optional(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8") if path.exists() else ""
        except OSError:
            return ""
