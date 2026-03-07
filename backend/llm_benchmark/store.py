"""
Supabase persistence for benchmark results.

`ensure_table()` verifies the table is accessible (DDL must be run via migration).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

TABLE = "benchmark_results"

# SQL for Supabase SQL Editor (also saved in infra/migrations/005_create_benchmark_results.sql)
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS benchmark_results (
    id           BIGSERIAL PRIMARY KEY,
    task_id      TEXT NOT NULL,
    category     TEXT NOT NULL,
    provider     TEXT NOT NULL,
    passed       BOOLEAN NOT NULL,
    response     TEXT DEFAULT '',
    note         TEXT DEFAULT '',
    latency_s    FLOAT NOT NULL,
    tokens_used  INT DEFAULT 0,
    error        TEXT DEFAULT '',
    run_at       TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bench_provider  ON benchmark_results (provider);
CREATE INDEX IF NOT EXISTS idx_bench_category  ON benchmark_results (category);
CREATE INDEX IF NOT EXISTS idx_bench_run_at    ON benchmark_results (run_at DESC);
"""


class BenchmarkStore:
    def __init__(self, db_client=None):
        if db_client is not None:
            self._db = db_client
        else:
            from app.db import get_client
            self._db = get_client()

    def ensure_table(self) -> bool:
        """Check table is reachable. Returns True if OK."""
        try:
            self._db.table(TABLE).select("id").limit(1).execute()
            return True
        except Exception as e:
            log.error(
                "benchmark_results table not accessible: %s. "
                "Run infra/migrations/005_create_benchmark_results.sql first.", e
            )
            return False

    def insert_result(
        self,
        task_id: str,
        category: str,
        provider: str,
        passed: bool,
        response: str,
        note: str,
        latency_s: float,
        tokens_used: int,
        error: str = "",
    ) -> Optional[dict]:
        try:
            res = self._db.table(TABLE).insert({
                "task_id":     task_id,
                "category":    category,
                "provider":    provider,
                "passed":      passed,
                "response":    response[:1000],
                "note":        note[:200],
                "latency_s":   latency_s,
                "tokens_used": tokens_used,
                "error":       error[:200],
                "run_at":      datetime.now(timezone.utc).isoformat(),
            }).execute()
            return res.data[0] if res.data else None
        except Exception as e:
            log.error("insert_result failed: %s", e)
            return None

    def latest_results(
        self,
        category: Optional[str] = None,
        limit: int = 500,
    ) -> list[dict]:
        """Fetch the most recent benchmark results, optionally filtered by category."""
        try:
            q = self._db.table(TABLE).select("*").order("run_at", desc=True).limit(limit)
            if category:
                q = q.eq("category", category)
            return q.execute().data or []
        except Exception as e:
            log.error("latest_results failed: %s", e)
            return []

    def provider_summary(self, since_hours: int = 168) -> list[dict]:
        """
        Aggregate pass-rate and avg latency per provider for the last N hours.
        Returns list of {provider, tasks_run, tasks_passed, accuracy, avg_latency_s}.
        """
        rows = self.latest_results(limit=2000)
        by_provider: dict[str, dict] = {}
        for row in rows:
            p = row["provider"]
            if p not in by_provider:
                by_provider[p] = {"tasks_run": 0, "tasks_passed": 0, "latency_sum": 0.0}
            by_provider[p]["tasks_run"] += 1
            if row["passed"]:
                by_provider[p]["tasks_passed"] += 1
            by_provider[p]["latency_sum"] += row.get("latency_s", 0.0)

        summary = []
        for provider, agg in by_provider.items():
            n = agg["tasks_run"]
            summary.append({
                "provider":     provider,
                "tasks_run":    n,
                "tasks_passed": agg["tasks_passed"],
                "accuracy":     round(agg["tasks_passed"] / n, 3) if n else 0.0,
                "avg_latency_s": round(agg["latency_sum"] / n, 3) if n else 0.0,
            })
        return sorted(summary, key=lambda x: x["accuracy"], reverse=True)
