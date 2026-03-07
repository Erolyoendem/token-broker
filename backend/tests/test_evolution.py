"""
Tests for the evolution system:
  - MetricsCollector: recording and querying
  - ExperimentManager: A/B test lifecycle and evaluation
  - AutoOptimizer: Thompson Sampling selection, threshold alerts, lessons
  - VersionControl: save/load/list configs
  - API endpoints: /evolution/*
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

os.environ.setdefault("ADMIN_API_KEY", "test_admin_key")

# ── MetricsCollector ──────────────────────────────────────────────────────────

from evolution.metrics_collector import MetricsCollector


@pytest.fixture()
def mc(tmp_path):
    return MetricsCollector(db_path=tmp_path / "test_metrics.db")


def test_metrics_record_and_retrieve(mc):
    mc.record(agent_id="gen-1", provider="nvidia", success=True,  tokens=300, latency_s=1.2, score=0.9)
    mc.record(agent_id="gen-1", provider="nvidia", success=True,  tokens=400, latency_s=0.8, score=0.85)
    mc.record(agent_id="gen-1", provider="deepseek", success=False, tokens=100, latency_s=3.0, score=0.2)

    stats = mc.get_stats(last_hours=24)
    assert len(stats) == 2

    by_provider = {r["provider"]: r for r in stats}
    assert by_provider["nvidia"]["calls"] == 2
    assert by_provider["nvidia"]["successes"] == 2
    assert by_provider["nvidia"]["success_rate_pct"] == 100.0
    assert by_provider["deepseek"]["successes"] == 0
    assert by_provider["deepseek"]["success_rate_pct"] == 0.0


def test_metrics_daily_trend(mc):
    for _ in range(5):
        mc.record(agent_id="a", provider="nvidia", success=True, tokens=100, latency_s=1.0)
    trend = mc.get_daily_trend(days=7)
    assert len(trend) >= 1
    assert trend[-1]["calls"] == 5
    assert trend[-1]["success_rate_pct"] == 100.0


def test_metrics_provider_history(mc):
    mc.record(agent_id="a", provider="nvidia", success=True)
    mc.record(agent_id="a", provider="nvidia", success=True)
    mc.record(agent_id="a", provider="nvidia", success=False)

    hist = mc.provider_history("nvidia")
    assert hist["successes"] == 2
    assert hist["failures"] == 1


def test_metrics_empty_stats(mc):
    assert mc.get_stats() == []
    assert mc.get_daily_trend() == []


def test_metrics_clear(mc):
    mc.record(agent_id="a", provider="nvidia", success=True)
    mc.clear()
    assert mc.get_stats() == []


# ── ExperimentManager ─────────────────────────────────────────────────────────

from evolution.experiment_manager import ExperimentManager


@pytest.fixture()
def em(tmp_path):
    return ExperimentManager(state_path=tmp_path / "experiments.json")


def test_experiment_create_and_assign(em):
    em.create("test_exp", variants=[
        {"name": "control",   "model": "nvidia"},
        {"name": "treatment", "model": "deepseek"},
    ])
    variant = em.assign("test_exp")
    assert variant["name"] in ("control", "treatment")


def test_experiment_requires_two_variants(em):
    with pytest.raises(ValueError, match="2 variants"):
        em.create("bad", variants=[{"name": "only"}])


def test_experiment_duplicate_raises(em):
    em.create("dup", variants=[{"name": "a"}, {"name": "b"}])
    with pytest.raises(ValueError, match="already exists"):
        em.create("dup", variants=[{"name": "a"}, {"name": "b"}])


def test_experiment_record_and_summary(em):
    em.create("quality", variants=[{"name": "v1"}, {"name": "v2"}])

    # v1: 3 successes, 1 failure
    em.record_outcome("quality", "v1", success=True,  score=0.9)
    em.record_outcome("quality", "v1", success=True,  score=0.85)
    em.record_outcome("quality", "v1", success=True,  score=0.88)
    em.record_outcome("quality", "v1", success=False, score=0.2)

    # v2: 1 success, 2 failures
    em.record_outcome("quality", "v2", success=True,  score=0.6)
    em.record_outcome("quality", "v2", success=False, score=0.1)
    em.record_outcome("quality", "v2", success=False, score=0.15)

    summary = em.summary("quality")
    assert summary["suggested_winner"] == "v1"  # higher success rate

    by_name = {v["name"]: v for v in summary["variants"]}
    assert by_name["v1"]["success_rate"] == pytest.approx(0.75)
    assert by_name["v2"]["success_rate"] == pytest.approx(1/3, rel=0.01)


def test_experiment_stop_and_freeze(em):
    em.create("lifecycle", variants=[{"name": "a"}, {"name": "b"}])
    em.record_outcome("lifecycle", "a", success=True)
    em.stop("lifecycle")
    with pytest.raises(RuntimeError, match="not running"):
        em.assign("lifecycle")

    em2 = ExperimentManager(state_path=em._path)
    em2.freeze("lifecycle", "a")
    summary = em2.summary("lifecycle")
    assert summary["winner"] == "a"


def test_experiment_unknown_raises(em):
    with pytest.raises(KeyError):
        em.assign("nonexistent")


# ── AutoOptimizer ─────────────────────────────────────────────────────────────

from evolution.auto_optimizer import AutoOptimizer


@pytest.fixture()
def opt(mc):
    return AutoOptimizer(mc)


def test_optimizer_prefers_better_provider(mc, opt):
    # Seed nvidia with many successes, deepseek with many failures
    for _ in range(50):
        mc.record(agent_id="a", provider="nvidia",   success=True)
    for _ in range(50):
        mc.record(agent_id="a", provider="deepseek", success=False)

    # With fixed seed, should consistently prefer nvidia
    selections = [opt.select_provider(["nvidia", "deepseek"], seed=i) for i in range(20)]
    nvidia_count = selections.count("nvidia")
    # With 50 successes vs 50 failures, nvidia should win the vast majority
    assert nvidia_count >= 15


def test_optimizer_explores_unknown(mc, opt):
    # No history – should still return a valid provider
    result = opt.select_provider(["nvidia", "deepseek"], seed=42)
    assert result in ("nvidia", "deepseek")


def test_optimizer_single_candidate(mc, opt):
    assert opt.select_provider(["nvidia"]) == "nvidia"


def test_optimizer_empty_candidates(mc, opt):
    with pytest.raises(ValueError):
        opt.select_provider([])


def test_optimizer_check_thresholds_no_data(mc, opt):
    alerts = opt.check_thresholds()
    assert alerts == []


def test_optimizer_check_thresholds_detects_low_rate(mc, opt):
    for _ in range(3):
        mc.record(agent_id="a", provider="nvidia", success=False, latency_s=1.0)
    for _ in range(7):
        mc.record(agent_id="a", provider="nvidia", success=True,  latency_s=1.0)

    # 30% failure rate → below 0.6 floor
    mc.clear()
    for _ in range(7):
        mc.record(agent_id="a", provider="nvidia", success=False, latency_s=1.0)
    for _ in range(3):
        mc.record(agent_id="a", provider="nvidia", success=True,  latency_s=1.0)

    alerts = opt.check_thresholds(success_rate_floor=0.6)
    assert any(a["type"] == "low_success_rate" and a["provider"] == "nvidia" for a in alerts)


def test_optimizer_check_thresholds_detects_latency(mc, opt):
    for _ in range(5):
        mc.record(agent_id="a", provider="deepseek", success=True, latency_s=15.0)
    alerts = opt.check_thresholds(latency_ceil_s=10.0)
    assert any(a["type"] == "high_latency" and a["provider"] == "deepseek" for a in alerts)


def test_optimizer_lessons_no_data(mc, opt):
    lessons = opt.lessons_learned()
    assert len(lessons) == 1
    assert "No data" in lessons[0]


def test_optimizer_lessons_with_data(mc, opt):
    for _ in range(10):
        mc.record(agent_id="a", provider="nvidia",   success=True,  latency_s=1.0)
    for _ in range(5):
        mc.record(agent_id="a", provider="deepseek", success=False, latency_s=3.0)

    lessons = opt.lessons_learned()
    assert len(lessons) >= 3
    assert any("nvidia" in l for l in lessons)


def test_optimizer_provider_scores(mc, opt):
    mc.record(agent_id="a", provider="nvidia", success=True)
    mc.record(agent_id="a", provider="nvidia", success=True)
    mc.record(agent_id="a", provider="deepseek", success=False)

    scores = opt.provider_scores(["nvidia", "deepseek"])
    assert scores[0]["provider"] == "nvidia"   # higher success rate first
    assert scores[0]["alpha"] == 3             # 2 successes + 1
    assert scores[1]["beta"] == 2              # 1 failure + 1


# ── VersionControl ────────────────────────────────────────────────────────────

from evolution.version_control import VersionControl


@pytest.fixture()
def vc(tmp_path):
    configs_dir = tmp_path / "configs"
    repo_root = tmp_path  # won't be a real git repo – git tag will silently fail
    return VersionControl(configs_dir=configs_dir, repo_root=repo_root)


def test_vc_save_and_load(vc):
    cfg = {"provider": "nvidia", "score": 0.92, "prompt": "You are an expert."}
    tag = vc.save_config("test-config", config=cfg, message="Test save", tag=False)
    assert tag.startswith("evo-test-config-")

    loaded = vc.load_config(tag)
    assert loaded["config"]["provider"] == "nvidia"
    assert loaded["config"]["score"] == 0.92
    assert loaded["message"] == "Test save"


def test_vc_list_configs(vc):
    vc.save_config("alpha", config={"x": 1}, tag=False)
    vc.save_config("beta",  config={"x": 2}, tag=False)
    configs = vc.list_configs()
    assert len(configs) == 2
    names = [c["name"] for c in configs]
    assert "alpha" in names
    assert "beta" in names


def test_vc_load_missing_raises(vc):
    with pytest.raises(FileNotFoundError):
        vc.load_config("evo-nonexistent-20260101T0000")


def test_vc_list_git_tags_no_repo(vc):
    # Should not crash even without a valid git repo
    tags = vc.list_git_tags()
    assert isinstance(tags, list)


# ── API endpoints ─────────────────────────────────────────────────────────────

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
ADMIN = {"X-Admin-Key": "test_admin_key"}


def test_evolution_stats_requires_admin():
    resp = client.get("/evolution/stats", headers={"X-Admin-Key": "bad"})
    assert resp.status_code == 403


def test_evolution_stats_returns_structure():
    resp = client.get("/evolution/stats", headers=ADMIN)
    assert resp.status_code == 200
    assert "providers" in resp.json()


def test_evolution_trend_returns_structure():
    resp = client.get("/evolution/trend", headers=ADMIN)
    assert resp.status_code == 200
    assert "days" in resp.json()


def test_evolution_provider_scores():
    resp = client.get("/evolution/provider-scores", headers=ADMIN)
    assert resp.status_code == 200
    providers = resp.json()["providers"]
    assert isinstance(providers, list)
    names = [p["provider"] for p in providers]
    assert "nvidia" in names
    assert "deepseek" in names


def test_evolution_alerts():
    resp = client.get("/evolution/alerts", headers=ADMIN)
    assert resp.status_code == 200
    assert "alerts" in resp.json()


def test_evolution_lessons():
    resp = client.get("/evolution/lessons", headers=ADMIN)
    assert resp.status_code == 200
    assert "lessons" in resp.json()
    assert isinstance(resp.json()["lessons"], list)


def test_evolution_experiments_list():
    resp = client.get("/evolution/experiments", headers=ADMIN)
    assert resp.status_code == 200
    assert "experiments" in resp.json()


def test_evolution_experiment_stop_not_found():
    resp = client.post("/evolution/experiments/nonexistent/stop", headers=ADMIN)
    assert resp.status_code == 404


def test_evolution_configs_list():
    resp = client.get("/evolution/configs", headers=ADMIN)
    assert resp.status_code == 200
    assert "configs" in resp.json()
