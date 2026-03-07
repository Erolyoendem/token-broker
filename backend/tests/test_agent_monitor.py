"""
Tests for infra/agent_monitor.py

Covers:
  - collect_agent_metrics(): empty state, full state, corrupt file
  - check_agent_health(): above/below threshold, per-variant alerts
  - generate_agent_report(): file creation, Markdown structure
  - _AlertLog: log_alert accumulates entries
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Make infra importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "infra"))

from agent_monitor import (
    _AlertLog,
    _empty_metrics,
    _read_memory_json,
    check_agent_health,
    collect_agent_metrics,
    generate_agent_report,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_memory(
    tmp_path: Path,
    n_ok: int = 10,
    n_fail: int = 2,
    variants: dict | None = None,
) -> Path:
    """Write a synthetic memory.json and return its path."""
    convs = [
        {
            "filename": f"file_{i}.rb",
            "ruby_code": "",
            "python_code": "",
            "score": 0.9 if i < n_ok else 0.1,
            "tokens": 50 + i,
            "elapsed_s": 1.0 + i * 0.1,
            "prompt_variant": "v1_minimal" if i % 2 == 0 else "v2_structured",
            "error": "" if i < n_ok else f"error_{i}",
            "timestamp": "2026-03-07T00:00:00",
        }
        for i in range(n_ok + n_fail)
    ]
    default_variants = {
        "v1_minimal": {"calls": n_ok // 2, "successes": n_ok // 2 - 1, "total_tokens": 500},
        "v2_structured": {"calls": n_ok // 2 + n_fail, "successes": n_ok // 2, "total_tokens": 600},
    }
    state = {
        "conversions": convs,
        "prompt_variants": variants if variants is not None else default_variants,
        "run_summaries": [{"ok": n_ok, "errors": n_fail}],
        "meta": {"total_conversions": n_ok + n_fail, "total_tokens": 0,
                 "created_at": "", "last_updated": ""},
    }
    p = tmp_path / "memory.json"
    p.write_text(json.dumps(state))
    return p


# ── _AlertLog ─────────────────────────────────────────────────────────────────

class TestAlertLog:
    def test_log_alert_accumulates(self):
        log = _AlertLog()
        log.log_alert("warning", "test_source", "something low")
        log.log_alert("critical", "test_source", "something critical")
        recent = log.recent()
        assert len(recent) == 2
        assert recent[0]["level"] == "warning"
        assert recent[1]["level"] == "critical"

    def test_recent_respects_limit(self):
        log = _AlertLog()
        for i in range(60):
            log.log_alert("warning", f"src_{i}", f"msg_{i}")
        assert len(log.recent(10)) == 10
        assert len(log.recent(100)) == 60


# ── collect_agent_metrics ─────────────────────────────────────────────────────

class TestCollectAgentMetrics:
    def test_empty_memory_file_returns_zeros(self, tmp_path):
        missing = tmp_path / "missing.json"
        m = collect_agent_metrics(memory_path=missing)
        assert m["total_conversions"] == 0
        assert m["overall_success_rate"] == 0.0
        assert m["per_variant"] == {}

    def test_corrupt_file_returns_zeros(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("NOT_JSON{{{{")
        m = collect_agent_metrics(memory_path=p)
        assert m["total_conversions"] == 0

    def test_success_rate_computed_correctly(self, tmp_path):
        mem = _make_memory(tmp_path, n_ok=8, n_fail=2)
        m = collect_agent_metrics(memory_path=mem)
        assert m["total_conversions"] == 10
        assert m["overall_success_rate"] == pytest.approx(0.8, abs=0.01)

    def test_per_variant_keys_present(self, tmp_path):
        mem = _make_memory(tmp_path)
        m = collect_agent_metrics(memory_path=mem)
        assert "v1_minimal" in m["per_variant"]
        assert "v2_structured" in m["per_variant"]

    def test_top_variants_sorted_by_rate(self, tmp_path):
        mem = _make_memory(tmp_path, variants={
            "low":  {"calls": 10, "successes": 4, "total_tokens": 100},
            "high": {"calls": 10, "successes": 9, "total_tokens": 200},
        })
        m = collect_agent_metrics(memory_path=mem)
        rates = [v["success_rate"] for v in m["top_variants"]]
        assert rates == sorted(rates, reverse=True)

    def test_avg_tokens_positive(self, tmp_path):
        mem = _make_memory(tmp_path, n_ok=5, n_fail=1)
        m = collect_agent_metrics(memory_path=mem)
        assert m["avg_tokens"] > 0

    def test_source_key_present(self, tmp_path):
        mem = _make_memory(tmp_path)
        m = collect_agent_metrics(memory_path=mem)
        assert "source" in m

    def test_recent_errors_only_failures(self, tmp_path):
        mem = _make_memory(tmp_path, n_ok=5, n_fail=3)
        m = collect_agent_metrics(memory_path=mem)
        for e in m["recent_errors"]:
            assert e["error"]  # error field non-empty


# ── check_agent_health ────────────────────────────────────────────────────────

class TestCheckAgentHealth:
    def test_no_alerts_when_above_threshold(self, tmp_path):
        mem = _make_memory(tmp_path, n_ok=10, n_fail=0, variants={
            "v1": {"calls": 20, "successes": 18, "total_tokens": 200},
        })
        triggered = check_agent_health(threshold=0.7, memory_path=mem)
        assert triggered == []

    def test_overall_alert_when_below_threshold(self, tmp_path):
        mem = _make_memory(tmp_path, n_ok=3, n_fail=7)
        triggered = check_agent_health(threshold=0.7, memory_path=mem)
        sources = [a["source"] for a in triggered]
        assert "overall" in sources

    def test_variant_alert_when_below_threshold(self, tmp_path):
        mem = _make_memory(tmp_path, n_ok=10, n_fail=0, variants={
            "bad_variant": {"calls": 10, "successes": 3, "total_tokens": 100},
        })
        triggered = check_agent_health(threshold=0.7, memory_path=mem)
        sources = [a["source"] for a in triggered]
        assert "bad_variant" in sources

    def test_no_alert_for_low_call_count(self, tmp_path):
        """Variants with < 5 calls should not trigger alerts."""
        mem = _make_memory(tmp_path, n_ok=10, n_fail=0, variants={
            "new_variant": {"calls": 2, "successes": 0, "total_tokens": 0},
        })
        triggered = check_agent_health(threshold=0.7, memory_path=mem)
        sources = [a["source"] for a in triggered]
        assert "new_variant" not in sources

    def test_returns_list(self, tmp_path):
        missing = tmp_path / "missing.json"
        result = check_agent_health(memory_path=missing)
        assert isinstance(result, list)


# ── generate_agent_report ─────────────────────────────────────────────────────

class TestGenerateAgentReport:
    def test_creates_markdown_file(self, tmp_path):
        mem = _make_memory(tmp_path)
        report_dir = tmp_path / "reports"
        path = generate_agent_report(memory_path=mem, output_dir=report_dir)
        assert path.exists()
        assert path.suffix == ".md"

    def test_report_contains_expected_sections(self, tmp_path):
        mem = _make_memory(tmp_path)
        path = generate_agent_report(memory_path=mem, output_dir=tmp_path / "r")
        content = path.read_text()
        assert "## Summary" in content
        assert "## Prompt Variant Performance" in content
        assert "## Health Alerts" in content

    def test_report_filename_includes_week(self, tmp_path):
        mem = _make_memory(tmp_path)
        path = generate_agent_report(memory_path=mem, output_dir=tmp_path / "r")
        now = datetime.now(timezone.utc)
        assert now.strftime("%Y-W%W") in path.name or now.strftime("%Y-%W") in path.name

    def test_report_shows_variant_stats(self, tmp_path):
        mem = _make_memory(tmp_path)
        path = generate_agent_report(memory_path=mem, output_dir=tmp_path / "r")
        content = path.read_text()
        assert "v1_minimal" in content or "v2_structured" in content

    def test_report_created_for_empty_memory(self, tmp_path):
        missing = tmp_path / "missing.json"
        path = generate_agent_report(memory_path=missing, output_dir=tmp_path / "r")
        assert path.exists()
        content = path.read_text()
        assert "0" in content  # zero conversions shown

    def test_creates_output_dir_if_missing(self, tmp_path):
        mem = _make_memory(tmp_path)
        nested = tmp_path / "a" / "b" / "c"
        path = generate_agent_report(memory_path=mem, output_dir=nested)
        assert nested.exists()
        assert path.exists()
