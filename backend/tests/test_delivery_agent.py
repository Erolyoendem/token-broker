"""
Tests für den Delivery-Agent – vollständiger Job-Lebenszyklus.

Simuliert alle Phasen: pending → assessment → planning → executing → validating → done
sowie Fehler-, Rollback- und Cancel-Szenarien.
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import patch, MagicMock

from delivery_agent.orchestrator import (
    DeliveryOrchestrator, DeliveryJob, JobStatus, get_job, _JOB_STORE,
)
from delivery_agent.resource_manager import DeliveryResourceManager
from delivery_agent.quality_gate import QualityGate, QualityResult
from delivery_agent.client_portal import get_job_status, format_progress_bar


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_job(description: str = "Migrate Ruby app to Python") -> DeliveryJob:
    job = DeliveryJob(
        id="test-job-0001",
        customer_id="cust-uuid-0001",
        description=description,
    )
    _JOB_STORE[job.id] = job
    return job


def _completed_job() -> DeliveryJob:
    """A job with execution_result set so QualityGate can pass."""
    job = _make_job()
    job.plan["execution_result"] = {
        "steps_completed": 3,
        "ok": True,
        "score": 0.9,
        "tokens_used": 10_000,
    }
    return job


# ── DeliveryJob unit tests ─────────────────────────────────────────────────────

def test_job_initial_status():
    job = _make_job()
    assert job.status == JobStatus.PENDING
    assert job.progress == 0
    assert job.logs == []


def test_job_log_appends():
    job = _make_job()
    job.log("Step 1 done")
    assert len(job.logs) == 1
    assert "Step 1 done" in job.logs[0]


def test_job_to_dict_keys():
    job = _make_job()
    d = job.to_dict()
    for key in ("id", "customer_id", "status", "progress", "logs", "plan"):
        assert key in d


# ── QualityGate tests ──────────────────────────────────────────────────────────

def test_quality_gate_passes_clean_job():
    gate = QualityGate()
    job = _completed_job()
    result = gate.validate(job)
    assert result.passed
    assert result.checks["execution_completed"]
    assert result.checks["no_critical_errors"]


def test_quality_gate_fails_no_steps():
    gate = QualityGate()
    job = _make_job()
    job.plan["execution_result"] = {"steps_completed": 0, "ok": False}
    result = gate.validate(job)
    assert not result.passed
    assert "steps" in result.reason.lower()


def test_quality_gate_fails_on_error_keyword():
    gate = QualityGate()
    job = _completed_job()
    job.logs.append("Fatal traceback in conversion")
    result = gate.validate(job)
    assert not result.passed
    assert "traceback" in result.reason or "Critical" in result.reason


def test_quality_gate_fails_below_score():
    gate = QualityGate(min_score=0.8)
    job = _completed_job()
    job.plan["execution_result"]["score"] = 0.3
    result = gate.validate(job)
    assert not result.passed
    assert "0.30" in result.reason or "threshold" in result.reason


def test_quality_gate_fails_token_budget():
    gate = QualityGate(max_tokens=1_000)
    job = _completed_job()
    job.plan["execution_result"]["tokens_used"] = 50_000
    result = gate.validate(job)
    assert not result.passed
    assert "budget" in result.reason.lower()


def test_quality_result_to_dict():
    r = QualityResult(passed=True, reason="ok", checks={"a": True}, score=0.9)
    d = r.to_dict()
    assert d["passed"] is True
    assert d["score"] == 0.9


# ── ResourceManager tests ──────────────────────────────────────────────────────

def test_resource_manager_check_quota_ok():
    rm = DeliveryResourceManager()
    ok, reason = rm.check_quota("cust-001")
    assert ok
    assert reason == "ok"


def test_resource_manager_reserve_release():
    rm = DeliveryResourceManager()
    rm.reserve("cust-001", "job-A")
    assert "job-A" in rm.get_quota("cust-001").active_jobs
    rm.release("cust-001", "job-A")
    assert "job-A" not in rm.get_quota("cust-001").active_jobs


def test_resource_manager_parallel_limit():
    rm = DeliveryResourceManager()
    quota = rm.get_quota("cust-limit")
    quota.max_parallel = 1
    rm.reserve("cust-limit", "job-1")
    ok, reason = rm.check_quota("cust-limit")
    assert not ok
    assert "Max parallel" in reason


def test_resource_manager_token_budget_exhausted():
    rm = DeliveryResourceManager()
    quota = rm.get_quota("cust-budget")
    quota.monthly_tokens = 1000
    quota.tokens_used = 1000
    ok, reason = rm.check_quota("cust-budget")
    assert not ok
    assert "budget" in reason.lower()


def test_resource_manager_usage_summary():
    rm = DeliveryResourceManager()
    rm.reserve("cust-s", "job-X")
    summary = rm.usage_summary("cust-s")
    assert summary["parallel_count"] == 1
    assert "cust-s" == summary["customer_id"]


# ── ClientPortal tests ─────────────────────────────────────────────────────────

def test_format_progress_bar_empty():
    bar = format_progress_bar(0)
    assert bar.startswith("[░")
    assert "0%" in bar


def test_format_progress_bar_full():
    bar = format_progress_bar(100)
    assert "100%" in bar
    assert "░" not in bar


def test_format_progress_bar_half():
    bar = format_progress_bar(50)
    assert "50%" in bar


def test_get_job_status_returns_public_fields():
    job = _completed_job()
    job.status = JobStatus.DONE
    job.progress = 100
    _JOB_STORE[job.id] = job

    status = get_job_status(job.id)
    assert status is not None
    assert status["job_id"] == job.id
    assert status["status"] == JobStatus.DONE
    assert "progress_bar" in status
    assert "recent_logs" in status


def test_get_job_status_not_found():
    result = get_job_status("non-existent-id")
    assert result is None


# ── Full lifecycle (async) ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_job_lifecycle_success():
    """Simulates a complete job run from pending → done."""
    gate = QualityGate()
    rm   = DeliveryResourceManager()
    orch = DeliveryOrchestrator(quality_gate=gate, resource_manager=rm)

    job = orch.create_job("cust-e2e", "Migrate calculator.rb to Python")

    # Patch execution to set a passing result
    async def _mock_executing(j):
        j.plan["execution_result"] = {
            "steps_completed": 2, "ok": True, "score": 0.95, "tokens_used": 5_000
        }
        j.progress = 80

    with patch.object(orch, "_phase_executing", side_effect=_mock_executing):
        completed = await orch.run(job)

    assert completed.status == JobStatus.DONE
    assert completed.progress == 100
    assert completed.completed_at != ""
    # Verify all phases logged
    phase_logs = " ".join(completed.logs)
    for phase in ("assessment", "planning", "executing", "validating"):
        assert phase in phase_logs


@pytest.mark.asyncio
async def test_job_fails_on_resource_exhaustion():
    """Job fails when customer's parallel limit is hit."""
    rm = DeliveryResourceManager()
    quota = rm.get_quota("cust-fail")
    quota.max_parallel = 0  # no capacity

    orch = DeliveryOrchestrator(resource_manager=rm)
    job  = orch.create_job("cust-fail", "Blocked job")

    completed = await orch.run(job)
    assert completed.status == JobStatus.FAILED
    assert any("quota" in l.lower() or "resource" in l.lower() for l in completed.logs)


@pytest.mark.asyncio
async def test_job_cancel():
    orch = DeliveryOrchestrator()
    job  = orch.create_job("cust-cancel", "Job to cancel")
    _JOB_STORE[job.id] = job

    cancelled = orch.cancel(job.id)
    assert cancelled is True

    updated = get_job(job.id)
    assert updated.status == JobStatus.CANCELLED


@pytest.mark.asyncio
async def test_cancel_already_done_returns_false():
    orch = DeliveryOrchestrator()
    job  = orch.create_job("cust-done", "Already done")
    job.status = JobStatus.DONE
    _JOB_STORE[job.id] = job

    result = orch.cancel(job.id)
    assert result is False


@pytest.mark.asyncio
async def test_quality_gate_retry_on_failure():
    """Quality gate failure triggers retry; second attempt succeeds."""
    gate = QualityGate()
    rm   = DeliveryResourceManager()
    orch = DeliveryOrchestrator(quality_gate=gate, resource_manager=rm)
    job  = orch.create_job("cust-retry", "Retry test job")

    call_count = {"n": 0}

    async def _mock_executing(j):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First attempt: bad result → gate fails
            j.plan["execution_result"] = {
                "steps_completed": 1, "ok": True, "score": 0.1, "tokens_used": 0
            }
        else:
            # Second attempt: good result
            j.plan["execution_result"] = {
                "steps_completed": 2, "ok": True, "score": 0.95, "tokens_used": 1_000
            }
        j.progress = 80

    with patch.object(orch, "_phase_executing", side_effect=_mock_executing):
        completed = await orch.run(job)

    assert completed.status == JobStatus.DONE
    assert call_count["n"] == 2  # executed twice (initial + retry)


# ── get_job persistence ────────────────────────────────────────────────────────

def test_get_job_returns_stored_job():
    job = _make_job("Persistence test")
    retrieved = get_job(job.id)
    assert retrieved is not None
    assert retrieved.id == job.id
    assert retrieved.description == "Persistence test"
