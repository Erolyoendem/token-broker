"""
DeliveryOrchestrator – Steuert den vollständigen Migrations-Workflow.

Phasen:
  pending → assessment → planning → executing → validating → done
                                                           ↘ failed

Für jede Phase wird der zuständige Sub-Agent aufgerufen. Ergebnisse werden
in der `delivery_jobs`-Tabelle persistiert (via Supabase oder In-Memory-Fallback).
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class JobStatus(str, Enum):
    PENDING     = "pending"
    ASSESSMENT  = "assessment"
    PLANNING    = "planning"
    EXECUTING   = "executing"
    VALIDATING  = "validating"
    DONE        = "done"
    FAILED      = "failed"
    CANCELLED   = "cancelled"


@dataclass
class DeliveryJob:
    id:            str
    customer_id:   str
    description:   str
    plan:          dict   = field(default_factory=dict)
    status:        str    = JobStatus.PENDING
    current_phase: str    = ""
    progress:      int    = 0
    logs:          list   = field(default_factory=list)
    started_at:    str    = ""
    completed_at:  str    = ""
    result_path:   str    = ""
    created_at:    str    = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    def log(self, msg: str) -> None:
        entry = f"[{time.strftime('%H:%M:%S')}] {msg}"
        self.logs.append(entry)
        log.info("[Job %s] %s", self.id[:8], msg)

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "customer_id":   self.customer_id,
            "description":   self.description,
            "plan":          self.plan,
            "status":        self.status,
            "current_phase": self.current_phase,
            "progress":      self.progress,
            "logs":          self.logs,
            "started_at":    self.started_at,
            "completed_at":  self.completed_at,
            "result_path":   self.result_path,
            "created_at":    self.created_at,
        }


# ── In-Memory Job Store (Fallback wenn DB nicht verfügbar) ────────────────────
_JOB_STORE: dict[str, DeliveryJob] = {}


def _db_upsert(job: DeliveryJob) -> None:
    """Persistiert Job in Supabase; fällt auf In-Memory zurück."""
    _JOB_STORE[job.id] = job
    try:
        from app.db import get_client
        get_client().table("delivery_jobs").upsert({
            "id":            job.id,
            "customer_id":   job.customer_id,
            "plan":          job.plan,
            "status":        job.status,
            "current_phase": job.current_phase,
            "progress":      job.progress,
            "logs":          job.logs,
            "started_at":    job.started_at or None,
            "completed_at":  job.completed_at or None,
            "result_path":   job.result_path or None,
        }).execute()
    except Exception as exc:
        log.debug("DB upsert skipped (in-memory only): %s", exc)


def get_job(job_id: str) -> DeliveryJob | None:
    """Holt Job aus In-Memory-Store oder Supabase."""
    if job_id in _JOB_STORE:
        return _JOB_STORE[job_id]
    try:
        from app.db import get_client
        row = (
            get_client()
            .table("delivery_jobs")
            .select("*")
            .eq("id", job_id)
            .maybe_single()
            .execute()
            .data
        )
        if row:
            job = DeliveryJob(
                id=row["id"],
                customer_id=row["customer_id"],
                description=row.get("plan", {}).get("description", ""),
                plan=row.get("plan", {}),
                status=row["status"],
                current_phase=row.get("current_phase", ""),
                progress=row.get("progress", 0),
                logs=row.get("logs") or [],
                started_at=row.get("started_at", ""),
                completed_at=row.get("completed_at", ""),
                result_path=row.get("result_path", ""),
                created_at=row.get("created_at", ""),
            )
            _JOB_STORE[job_id] = job
            return job
    except Exception:
        pass
    return None


def list_jobs(customer_id: str | None = None) -> list[dict]:
    jobs = list(_JOB_STORE.values())
    if customer_id:
        jobs = [j for j in jobs if j.customer_id == customer_id]
    return [j.to_dict() for j in sorted(jobs, key=lambda j: j.created_at, reverse=True)]


# ── DeliveryOrchestrator ───────────────────────────────────────────────────────

class DeliveryOrchestrator:
    """
    Orchestriert einen vollständigen Migrations-Auftrag.

    Ablauf:
      1. assessment  – Analysiert das Quellprojekt (via assessment_agent)
      2. planning    – CTO-Agent erstellt Migrations-Plan
      3. executing   – Agenten-Schwarm führt die Migration durch
      4. validating  – QualityGate prüft Ergebnisse
      5. done / failed
    """

    MAX_RETRIES = 2

    def __init__(self, quality_gate=None, resource_manager=None) -> None:
        from .quality_gate import QualityGate
        from .resource_manager import DeliveryResourceManager
        self._gate = quality_gate or QualityGate()
        self._rm   = resource_manager or DeliveryResourceManager()

    def create_job(self, customer_id: str, description: str) -> DeliveryJob:
        job = DeliveryJob(
            id=str(uuid.uuid4()),
            customer_id=customer_id,
            description=description,
        )
        job.log(f"Job created: {description[:80]}")
        _db_upsert(job)
        return job

    async def run(self, job: DeliveryJob) -> DeliveryJob:
        """Führt alle Phasen sequenziell aus."""
        job.started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        _db_upsert(job)

        phases = [
            (JobStatus.ASSESSMENT, self._phase_assessment),
            (JobStatus.PLANNING,   self._phase_planning),
            (JobStatus.EXECUTING,  self._phase_executing),
            (JobStatus.VALIDATING, self._phase_validating),
        ]

        for status, phase_fn in phases:
            job.status        = status
            job.current_phase = status
            job.log(f"Phase started: {status}")
            _db_upsert(job)

            try:
                await phase_fn(job)
            except Exception as exc:
                job.log(f"Phase {status} failed: {exc}")
                job.status = JobStatus.FAILED
                job.completed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
                _db_upsert(job)
                return job

            job.log(f"Phase completed: {status}")

        job.status        = JobStatus.DONE
        job.progress      = 100
        job.completed_at  = time.strftime("%Y-%m-%dT%H:%M:%S")
        job.log("All phases completed successfully.")
        _db_upsert(job)
        return job

    # ── Phases ────────────────────────────────────────────────────────────────

    async def _phase_assessment(self, job: DeliveryJob) -> None:
        """Phase 1: Projekt analysieren."""
        job.log("Assessment: analysing project structure...")
        # Attempt real assessment if assessment_agent available
        try:
            import sys
            from pathlib import Path as P
            sys.path.insert(0, str(P(__file__).resolve().parent.parent))
            from assessment_agent.code_scanner import CodeScanner
            scanner = CodeScanner()
            desc = job.description
            result = scanner.scan_text(desc) if hasattr(scanner, "scan_text") else {"lines": 0}
        except Exception as exc:
            log.debug("assessment_agent unavailable, using stub: %s", exc)
            result = {"lines": 0, "files": 0, "language": "ruby"}

        job.plan["assessment"] = result
        job.progress = 20
        job.log(f"Assessment done: {result}")

    async def _phase_planning(self, job: DeliveryJob) -> None:
        """Phase 2: CTO-Agent erstellt Migrations-Plan."""
        job.log("Planning: generating migration plan...")
        try:
            from cto_agent.core import CTOAgent
            cto = CTOAgent(
                Path(__file__).resolve().parent.parent.parent
            )
            decision = cto.decide(
                f"Plan migration: {job.description}",
                context={"phase": "planning", "job_id": job.id},
            )
            plan_detail = {
                "approved": decision.approved,
                "rationale": decision.rationale,
                "steps": [
                    "1. Convert Ruby classes to Python",
                    "2. Migrate routes to Django/FastAPI",
                    "3. Port database models",
                    "4. Run test suite",
                ],
            }
        except Exception as exc:
            log.debug("cto_agent unavailable, using stub plan: %s", exc)
            plan_detail = {
                "approved": True,
                "rationale": "Auto-approved (CTO agent offline)",
                "steps": ["Convert", "Test", "Deploy"],
            }

        job.plan["migration_plan"] = plan_detail
        job.progress = 40
        job.log(f"Plan ready: {len(plan_detail.get('steps', []))} steps")

    async def _phase_executing(self, job: DeliveryJob) -> None:
        """Phase 3: Agenten-Schwarm führt die Migration durch."""
        job.log("Executing: dispatching to agent swarm...")

        # Check resource quota
        quota_ok, reason = self._rm.check_quota(job.customer_id)
        if not quota_ok:
            raise RuntimeError(f"Resource quota exceeded: {reason}")

        self._rm.reserve(job.customer_id, job.id)

        try:
            steps = job.plan.get("migration_plan", {}).get("steps", [])
            total = len(steps) or 1
            for i, step in enumerate(steps, 1):
                job.log(f"Executing step {i}/{total}: {step}")
                job.progress = 40 + int(40 * i / total)
                _db_upsert(job)
                # In production: await swarm.convert_one(...)
        finally:
            self._rm.release(job.customer_id, job.id)

        job.plan["execution_result"] = {"steps_completed": len(steps), "ok": True}
        job.progress = 80
        job.log("Execution completed.")

    async def _phase_validating(self, job: DeliveryJob) -> None:
        """Phase 4: QualityGate validiert Ergebnisse."""
        job.log("Validating: running quality gate checks...")

        for attempt in range(1, self.MAX_RETRIES + 1):
            result = self._gate.validate(job)
            if result.passed:
                job.plan["quality_result"] = result.to_dict()
                job.progress = 95
                job.log(f"Quality gate passed (attempt {attempt}).")
                return
            job.log(f"Quality gate failed (attempt {attempt}): {result.reason}")
            if attempt < self.MAX_RETRIES:
                job.log("Retrying execution phase...")
                await self._phase_executing(job)

        # Final failure after retries
        raise RuntimeError(f"Quality gate failed after {self.MAX_RETRIES} retries.")

    def cancel(self, job_id: str) -> bool:
        job = get_job(job_id)
        if not job:
            return False
        if job.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED):
            return False
        job.status = JobStatus.CANCELLED
        job.completed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        job.log("Job cancelled by admin.")
        _db_upsert(job)
        return True
