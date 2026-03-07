"""
LessonsManager – Maintains tasks/lessons.md with accumulated rules and insights.

File format:

  # Lessons & Rules

  ## Rules (machine-readable)
  RULE: token_cost_increase > 20% → reject
  RULE: success_rate < 70% → alert

  ## Insights
  - 2026-03-07: DeepSeek fallback reduced cost by 35% on average
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any


_RULE_SECTION = "## Rules (machine-readable)"
_INSIGHTS_SECTION = "## Insights"

_INITIAL = """\
# Lessons & Rules

## Rules (machine-readable)
RULE: token_cost_increase > 20% → reject
RULE: success_rate < 70% → alert
RULE: provider == "unknown" → reject

## Insights
"""


class LessonsManager:
    """
    Reads/writes tasks/lessons.md.

    Usage::

        mgr = LessonsManager(Path("tasks/lessons.md"))
        mgr.add_insight("DeepSeek reduced cost by 35%")
        mgr.add_rule("latency > 30s → alert")
        rules = mgr.extract_rules()
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._ensure_exists()

    # ── Public API ────────────────────────────────────────────────────────────

    def add_insight(self, text: str) -> None:
        """Append a timestamped insight to the Insights section."""
        content = self._read()
        entry = f"- {time.strftime('%Y-%m-%d')}: {text.strip()}"
        if _INSIGHTS_SECTION in content:
            content = content.replace(
                _INSIGHTS_SECTION,
                _INSIGHTS_SECTION + "\n" + entry,
            )
        else:
            content += f"\n{_INSIGHTS_SECTION}\n{entry}\n"
        self._write(content)

    def add_rule(self, rule_text: str) -> None:
        """
        Append a new RULE line. rule_text should be:
          "condition → action"   e.g. "latency > 30s → alert"
        """
        rule_text = rule_text.strip()
        if not rule_text.upper().startswith("RULE:"):
            rule_text = f"RULE: {rule_text}"

        content = self._read()
        if rule_text in content:
            return  # deduplicate

        if _RULE_SECTION in content:
            content = content.replace(
                _RULE_SECTION,
                _RULE_SECTION + "\n" + rule_text,
            )
        else:
            content = f"{_RULE_SECTION}\n{rule_text}\n\n" + content
        self._write(content)

    def extract_rules(self) -> list[str]:
        """Return all RULE: lines as raw strings."""
        content = self._read()
        return re.findall(r"^RULE:.*$", content, re.M)

    def derive_rules_from_insights(self) -> list[str]:
        """
        Heuristically derive new rules from insight lines that contain
        quantitative observations (%, ratio, comparison operators).
        Returns list of new rule strings that were added.
        """
        content = self._read()
        existing_rules = set(self.extract_rules())
        new_rules: list[str] = []

        # Pattern: "X reduced/increased Y by Z%" → cost/token rule
        for m in re.finditer(
            r"(\w[\w\s]+?)\s+(?:increased|raised|grew)\s+(?:cost|token).*?by\s+([\d.]+)%",
            content, re.I
        ):
            pct = float(m.group(2))
            if pct > 20:
                rule = f"RULE: token_cost_increase > {pct:.0f}% → reject"
                if rule not in existing_rules:
                    new_rules.append(rule)

        # Pattern: "success rate of Z%" → success_rate rule
        for m in re.finditer(r"success rate.*?([\d.]+)%", content, re.I):
            pct = float(m.group(1))
            if pct < 70:
                rule = f"RULE: success_rate < {pct:.0f}% → alert"
                if rule not in existing_rules:
                    new_rules.append(rule)

        for r in new_rules:
            self.add_rule(r)

        return new_rules

    def read_all(self) -> str:
        return self._read()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _ensure_exists(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write(_INITIAL)

    def _read(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError:
            return _INITIAL

    def _write(self, content: str) -> None:
        self.path.write_text(content, encoding="utf-8")
