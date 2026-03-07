"""
Tests for the CTO Agent system.

Covers:
  - CTOAgent: config loading, context loading, decide(), summary()
  - Validator / RuleEngine: rule parsing, evaluation, hard constraints
  - Planner: task extraction, priority assignment, todo.md generation
  - LessonsManager: add_insight, add_rule, extract_rules, derive_rules
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from cto_agent.core import CTOAgent, ProjectConfig
from cto_agent.validator import Decision, Rule, RuleEngine, Validator
from cto_agent.planner import Planner, Task
from cto_agent.lessons import LessonsManager


# ── Fixtures ──────────────────────────────────────────────────────────────────

LESSONS_WITH_RULES = """\
# Lessons & Rules

## Rules (machine-readable)
RULE: token_cost_increase > 20% → reject
RULE: success_rate < 70% → alert
RULE: provider == "unknown" → reject

## Insights
- 2026-03-07: Test insight
"""

NEXT_SESSION_SAMPLE = """\
# Next Session

## Open Tasks

- Fix critical bug in payment endpoint
- Improve test coverage for agent swarm
- Refactor token router for better speed
- Document new CTO agent API
- Optional: cleanup legacy comments
"""


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    (tmp_path / "tasks").mkdir()
    return tmp_path


@pytest.fixture
def config_with_constraints(tmp_path: Path) -> ProjectConfig:
    import yaml
    cfg = {
        "token_cost_increase_limit": 0.20,
        "min_success_rate": 0.70,
        "max_batch_size": 50,
        "preferred_providers": ["nvidia", "deepseek"],
        "architecture_constraints": ["monolith", "synchronous_only"],
    }
    (tmp_path / "project_config.yaml").write_text(yaml.dump(cfg))
    return ProjectConfig.load(tmp_path / "project_config.yaml")


# ── ProjectConfig ─────────────────────────────────────────────────────────────

class TestProjectConfig:
    def test_defaults_when_no_file(self, tmp_path):
        cfg = ProjectConfig.load(tmp_path / "missing.yaml")
        assert cfg.token_cost_increase_limit == pytest.approx(0.20)
        assert cfg.min_success_rate == pytest.approx(0.70)
        assert "nvidia" in cfg.preferred_providers

    def test_loads_from_yaml(self, tmp_path):
        import yaml
        (tmp_path / "project_config.yaml").write_text(
            yaml.dump({"token_cost_increase_limit": 0.15, "min_success_rate": 0.80})
        )
        cfg = ProjectConfig.load(tmp_path / "project_config.yaml")
        assert cfg.token_cost_increase_limit == pytest.approx(0.15)
        assert cfg.min_success_rate == pytest.approx(0.80)

    def test_corrupt_yaml_returns_defaults(self, tmp_path):
        (tmp_path / "project_config.yaml").write_text("{{{{NOT YAML")
        cfg = ProjectConfig.load(tmp_path / "project_config.yaml")
        assert cfg.token_cost_increase_limit == pytest.approx(0.20)


# ── RuleEngine ────────────────────────────────────────────────────────────────

class TestRuleEngine:
    def test_parses_rules_from_text(self):
        engine = RuleEngine(LESSONS_WITH_RULES)
        assert len(engine.rules) == 3

    def test_reject_rule_triggers_on_high_cost(self):
        engine = RuleEngine(LESSONS_WITH_RULES)
        violations = engine.evaluate("Convert file.rb", {"token_cost_increase_pct": 25.0})
        assert any("20%" in v or "reject" in v.lower() for v in violations)

    def test_reject_rule_does_not_trigger_on_low_cost(self):
        engine = RuleEngine(LESSONS_WITH_RULES)
        violations = engine.evaluate("Convert file.rb", {"token_cost_increase_pct": 5.0})
        # The token_cost_increase rule should not fire
        token_violations = [v for v in violations if "token_cost" in v.lower()]
        assert token_violations == []

    def test_reject_rule_for_unknown_provider(self):
        engine = RuleEngine(LESSONS_WITH_RULES)
        violations = engine.evaluate("use provider", {"provider": "unknown"})
        assert any("unknown" in v.lower() or "reject" in v.lower() for v in violations)

    def test_empty_lessons_has_no_rules(self):
        engine = RuleEngine("")
        assert engine.rules == []

    def test_alert_rule_does_not_cause_violation(self):
        """Alert-level rules should not appear as violations (only reject/block do)."""
        engine = RuleEngine("RULE: success_rate < 70% → alert")
        violations = engine.evaluate("test", {"success_rate": 0.5})
        # alert action should NOT produce a violation (only reject/block do)
        assert violations == []


# ── Validator ─────────────────────────────────────────────────────────────────

class TestValidator:
    def _default_config(self) -> ProjectConfig:
        return ProjectConfig()

    def test_approves_clean_proposal(self):
        v = Validator(self._default_config(), LESSONS_WITH_RULES)
        violations = v.check_proposal("Add Redis cache", {})
        assert violations == []

    def test_rejects_high_token_cost(self):
        v = Validator(self._default_config(), LESSONS_WITH_RULES)
        violations = v.check_proposal("Switch provider", {"token_cost_increase_pct": 30.0})
        assert any("30" in vio or "cost" in vio.lower() for vio in violations)

    def test_rejects_low_success_rate(self):
        v = Validator(self._default_config(), LESSONS_WITH_RULES)
        violations = v.check_proposal("Run agent", {"success_rate": 0.50})
        assert any("success" in vio.lower() or "0.50" in vio or "50" in vio for vio in violations)

    def test_rejects_unknown_provider(self):
        v = Validator(self._default_config(), LESSONS_WITH_RULES)
        violations = v.check_proposal("Use provider", {"provider": "openai_unknown"})
        assert any("provider" in vio.lower() for vio in violations)

    def test_architecture_constraint_violation(self, config_with_constraints):
        v = Validator(config_with_constraints, "")
        violations = v.check_proposal("Migrate to monolith architecture", {})
        assert any("monolith" in vio.lower() for vio in violations)

    def test_no_violation_for_good_context(self):
        v = Validator(self._default_config(), LESSONS_WITH_RULES)
        violations = v.check_proposal(
            "Add caching layer",
            {"token_cost_increase_pct": 5.0, "success_rate": 0.95, "provider": "nvidia"},
        )
        assert violations == []


# ── CTOAgent.decide ───────────────────────────────────────────────────────────

class TestCTOAgentDecide:
    def test_approves_safe_proposal(self, project_root):
        cto = CTOAgent(project_root)
        d = cto.decide("Add logging to /chat endpoint", {"provider": "nvidia", "success_rate": 0.9})
        assert d.approved is True
        assert d.violations == []

    def test_rejects_cost_overshoot(self, project_root):
        cto = CTOAgent(project_root)
        d = cto.decide("Switch to expensive provider", {"token_cost_increase_pct": 50.0})
        assert d.approved is False
        assert len(d.violations) >= 1

    def test_decision_has_rationale(self, project_root):
        cto = CTOAgent(project_root)
        d = cto.decide("Any proposal", {})
        assert isinstance(d.rationale, str)
        assert len(d.rationale) > 0

    def test_summary_keys_present(self, project_root):
        cto = CTOAgent(project_root)
        s = cto.summary()
        assert "config" in s
        assert "active_rules" in s
        assert "lessons_loaded" in s


# ── Planner ───────────────────────────────────────────────────────────────────

class TestPlanner:
    def test_generates_todo_md(self, project_root):
        (project_root / "NEXT_SESSION.md").write_text(NEXT_SESSION_SAMPLE)
        planner = Planner(project_root)
        result = planner.generate_plan()
        assert (project_root / "tasks" / "todo.md").exists()
        assert result["total_tasks"] >= 1

    def test_critical_tasks_identified(self, project_root):
        (project_root / "NEXT_SESSION.md").write_text(NEXT_SESSION_SAMPLE)
        Planner(project_root).generate_plan()
        content = (project_root / "tasks" / "todo.md").read_text()
        assert "Priority 1" in content or "Critical" in content

    def test_nice_to_have_tasks_identified(self, project_root):
        (project_root / "NEXT_SESSION.md").write_text(NEXT_SESSION_SAMPLE)
        Planner(project_root).generate_plan()
        content = (project_root / "tasks" / "todo.md").read_text()
        assert "Priority 3" in content or "Nice" in content

    def test_missing_next_session_produces_empty_plan(self, project_root):
        planner = Planner(project_root)
        result = planner.generate_plan()
        # Should not crash, may have 0 tasks
        assert isinstance(result["total_tasks"], int)

    def test_task_priority_inference(self):
        t = Task("Fix critical security bug")
        t._infer_priority()
        assert t.priority == 1

    def test_optional_task_is_priority_3(self):
        t = Task("Optional: cleanup old docs")
        t._infer_priority()
        assert t.priority == 3

    def test_creates_tasks_dir_if_missing(self, tmp_path):
        # tasks/ dir does not exist yet
        (tmp_path / "NEXT_SESSION.md").write_text(NEXT_SESSION_SAMPLE)
        planner = Planner(tmp_path)
        planner.generate_plan()
        assert (tmp_path / "tasks" / "todo.md").exists()


# ── LessonsManager ────────────────────────────────────────────────────────────

class TestLessonsManager:
    def test_creates_file_if_missing(self, tmp_path):
        mgr = LessonsManager(tmp_path / "lessons.md")
        assert (tmp_path / "lessons.md").exists()

    def test_add_insight(self, tmp_path):
        mgr = LessonsManager(tmp_path / "lessons.md")
        mgr.add_insight("DeepSeek saved 35% tokens")
        content = mgr.read_all()
        assert "DeepSeek saved 35% tokens" in content

    def test_add_rule(self, tmp_path):
        mgr = LessonsManager(tmp_path / "lessons.md")
        mgr.add_rule("latency > 30s → alert")
        rules = mgr.extract_rules()
        assert any("latency" in r for r in rules)

    def test_add_rule_deduplicates(self, tmp_path):
        mgr = LessonsManager(tmp_path / "lessons.md")
        mgr.add_rule("RULE: test → reject")
        mgr.add_rule("RULE: test → reject")
        rules = [r for r in mgr.extract_rules() if "test" in r]
        assert len(rules) == 1

    def test_extract_rules_from_initial_content(self, tmp_path):
        mgr = LessonsManager(tmp_path / "lessons.md")
        rules = mgr.extract_rules()
        assert len(rules) >= 3  # default rules

    def test_derive_rules_from_insights(self, tmp_path):
        p = tmp_path / "lessons.md"
        p.write_text(LESSONS_WITH_RULES + "\n- 2026-03-07: Provider X increased cost by 35%\n")
        mgr = LessonsManager(p)
        new_rules = mgr.derive_rules_from_insights()
        # May or may not derive depending on pattern match; should not crash
        assert isinstance(new_rules, list)

    def test_rule_engine_uses_lessons(self, tmp_path):
        mgr = LessonsManager(tmp_path / "lessons.md")
        mgr.add_rule("expensive_provider == true → reject")
        rules = mgr.extract_rules()
        assert any("expensive_provider" in r for r in rules)
