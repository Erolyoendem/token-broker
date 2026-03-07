"""
FastAPI router for /llm-matrix endpoint.

Mount in main.py:
    from llm_benchmark.api import router as benchmark_router
    app.include_router(benchmark_router)
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from .matrix import BenchmarkMatrix, MatrixBuilder
from .runner import BenchmarkRun, BenchmarkRunner, RunResult
from .store import BenchmarkStore
from .tasks import CATEGORIES, TASK_MAP

router = APIRouter(prefix="/llm-matrix", tags=["benchmark"])

# In-memory cache of the latest matrix (refreshed by weekly job)
_cached_matrix: Optional[BenchmarkMatrix] = None
_cached_at: Optional[str] = None


def _get_store() -> BenchmarkStore:
    return BenchmarkStore()


def _build_matrix_from_db(category: Optional[str] = None) -> dict:
    """Reconstruct a matrix from stored benchmark_results rows."""
    store = _get_store()
    rows = store.latest_results(category=category, limit=2000)

    if not rows:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "providers": [],
            "note": "No benchmark results found. Run scripts/run_benchmark.py first.",
        }

    # Group into BenchmarkRun objects
    by_provider: dict[str, list] = {}
    for row in rows:
        p = row["provider"]
        by_provider.setdefault(p, []).append(row)

    runs: list[BenchmarkRun] = []
    for provider, provider_rows in by_provider.items():
        run = BenchmarkRun(provider=provider)
        for row in provider_rows:
            run.results.append(RunResult(
                task_id=row["task_id"],
                category=row["category"],
                provider=provider,
                passed=row["passed"],
                response=row.get("response", ""),
                note=row.get("note", ""),
                latency_s=row.get("latency_s", 0.0),
                tokens_used=row.get("tokens_used", 0),
                error=row.get("error", ""),
            ))
        runs.append(run)

    matrix = MatrixBuilder().build(runs)
    return matrix.as_dict()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
def get_matrix(
    category: Optional[str] = Query(None, description="Filter by task category"),
    refresh: bool = Query(False, description="Force rebuild from DB"),
):
    """
    Returns the current LLM benchmark matrix.

    - **category**: optional filter (math, code_gen, code_convert, factual, creative)
    - **refresh**: set true to rebuild from stored results
    """
    if category and category not in CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown category '{category}'. Valid: {CATEGORIES}",
        )

    global _cached_matrix, _cached_at
    if not refresh and _cached_matrix and not category:
        return {**_cached_matrix.as_dict(), "cached_at": _cached_at}

    return _build_matrix_from_db(category=category)


@router.get("/tasks")
def list_tasks(category: Optional[str] = Query(None)):
    """List all benchmark tasks, optionally filtered by category."""
    tasks = list(TASK_MAP.values())
    if category:
        tasks = [t for t in tasks if t.category == category]
    return {
        "total": len(tasks),
        "tasks": [
            {"id": t.id, "category": t.category, "difficulty": t.difficulty}
            for t in tasks
        ],
    }


@router.get("/categories")
def list_categories():
    """List all available task categories."""
    return {"categories": CATEGORIES}


@router.get("/providers")
def provider_summary():
    """Aggregated accuracy + latency per provider from stored results."""
    store = _get_store()
    return {"providers": store.provider_summary()}


def update_cache(matrix: BenchmarkMatrix) -> None:
    """Called by the weekly scheduler job after a fresh run."""
    global _cached_matrix, _cached_at
    _cached_matrix = matrix
    _cached_at = datetime.now(timezone.utc).isoformat()
