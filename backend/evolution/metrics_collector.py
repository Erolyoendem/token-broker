"""
MetricsCollector – SQLite-backed performance data store for agent runs.

Usage
-----
    from evolution.metrics_collector import MetricsCollector

    mc = MetricsCollector()           # default: evolution/metrics.db
    mc.record(
        agent_id="gen-nvidia",
        task_type="ruby_to_python",
        provider="nvidia",
        model="llama-3.1-70b",
        success=True,
        tokens=512,
        latency_s=1.23,
        score=0.87,
    )
    stats = mc.get_stats()            # aggregated per provider
    trends = mc.get_daily_trend()     # daily success rates
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).parent / "metrics.db"

_DDL = """
CREATE TABLE IF NOT EXISTS agent_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,
    agent_id    TEXT    NOT NULL,
    task_type   TEXT    NOT NULL DEFAULT 'unknown',
    provider    TEXT    NOT NULL,
    model       TEXT    NOT NULL DEFAULT '',
    success     INTEGER NOT NULL,   -- 1 / 0
    tokens      INTEGER NOT NULL DEFAULT 0,
    latency_s   REAL    NOT NULL DEFAULT 0.0,
    score       REAL    NOT NULL DEFAULT 0.0,
    experiment  TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ts       ON agent_runs (ts);
CREATE INDEX IF NOT EXISTS idx_provider ON agent_runs (provider);
CREATE INDEX IF NOT EXISTS idx_exp      ON agent_runs (experiment);
"""


class MetricsCollector:
    def __init__(self, db_path: Path | str = DEFAULT_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_DDL)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── Write ──────────────────────────────────────────────────────────────────

    def record(
        self,
        *,
        agent_id: str,
        provider: str,
        success: bool,
        task_type: str = "unknown",
        model: str = "",
        tokens: int = 0,
        latency_s: float = 0.0,
        score: float = 0.0,
        experiment: str = "",
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO agent_runs
                    (ts, agent_id, task_type, provider, model, success, tokens, latency_s, score, experiment)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    time.time(), agent_id, task_type, provider, model,
                    int(success), tokens, latency_s, score, experiment,
                ),
            )

    # ── Read ───────────────────────────────────────────────────────────────────

    def get_stats(self, last_hours: int = 24) -> list[dict[str, Any]]:
        """Aggregated stats per provider for the last N hours."""
        since = time.time() - last_hours * 3600
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT
                    provider,
                    COUNT(*)                         AS calls,
                    SUM(success)                     AS successes,
                    ROUND(AVG(success) * 100, 1)     AS success_rate_pct,
                    SUM(tokens)                      AS total_tokens,
                    ROUND(AVG(tokens), 1)            AS avg_tokens,
                    ROUND(AVG(latency_s), 3)         AS avg_latency_s,
                    ROUND(AVG(score), 3)             AS avg_score
                FROM agent_runs
                WHERE ts >= ?
                GROUP BY provider
                ORDER BY success_rate_pct DESC
                """,
                (since,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_daily_trend(self, days: int = 7) -> list[dict[str, Any]]:
        """Daily success rate and token usage for the last N days."""
        since = time.time() - days * 86400
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT
                    DATE(ts, 'unixepoch')            AS day,
                    COUNT(*)                         AS calls,
                    ROUND(AVG(success) * 100, 1)     AS success_rate_pct,
                    SUM(tokens)                      AS total_tokens,
                    ROUND(AVG(latency_s), 3)         AS avg_latency_s
                FROM agent_runs
                WHERE ts >= ?
                GROUP BY day
                ORDER BY day
                """,
                (since,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_experiment_rows(self, experiment: str) -> list[dict[str, Any]]:
        """All rows for a specific experiment (for A/B evaluation)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_runs WHERE experiment = ? ORDER BY ts",
                (experiment,),
            ).fetchall()
        return [dict(r) for r in rows]

    def provider_history(self, provider: str, task_type: str = "") -> dict[str, int]:
        """Return {successes, failures} for Thompson Sampling."""
        q = "SELECT SUM(success), COUNT(*) FROM agent_runs WHERE provider = ?"
        params: list[Any] = [provider]
        if task_type:
            q += " AND task_type = ?"
            params.append(task_type)
        with self._conn() as conn:
            row = conn.execute(q, params).fetchone()
        successes = int(row[0] or 0)
        total = int(row[1] or 0)
        return {"successes": successes, "failures": total - successes}

    def clear(self) -> None:
        """Remove all rows – useful for tests."""
        with self._conn() as conn:
            conn.execute("DELETE FROM agent_runs")
