"""
Supabase dataset manager for training pairs.

Schema (migration needed – see infra/migrations/004_create_training_pairs.sql):

    CREATE TABLE training_pairs (
        id              BIGSERIAL PRIMARY KEY,
        pair_id         TEXT NOT NULL,          -- e.g. 'ruby->python'
        source_lang     TEXT NOT NULL,
        target_lang     TEXT NOT NULL,
        source_code     TEXT NOT NULL,
        target_code     TEXT NOT NULL,
        source_url      TEXT,
        tokens_used     INT DEFAULT 0,
        provider        TEXT,
        quality_score   FLOAT,
        agent_ratings   JSONB,
        status          TEXT DEFAULT 'pending', -- pending | accepted | rejected | review
        created_at      TIMESTAMPTZ DEFAULT NOW()
    );
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class TrainingPair:
    pair_id: str
    source_lang: str
    target_lang: str
    source_code: str
    target_code: str
    source_url: str = ""
    tokens_used: int = 0
    provider: str = ""
    quality_score: float = 0.0
    agent_ratings: Optional[list[int]] = None
    status: str = "pending"


class DatasetManager:
    TABLE = "training_pairs"

    def __init__(self, supabase_client=None):
        """
        Accept an already-initialised Supabase client (injected for testability).
        Falls back to creating one from env vars if not provided.
        """
        if supabase_client is not None:
            self._db = supabase_client
        else:
            from app.db import get_client
            self._db = get_client()

    # ── Write ─────────────────────────────────────────────────────────────────

    def insert(self, pair: TrainingPair) -> dict:
        """Insert a single training pair. Returns the inserted row."""
        row = {
            "pair_id":       pair.pair_id,
            "source_lang":   pair.source_lang,
            "target_lang":   pair.target_lang,
            "source_code":   pair.source_code,
            "target_code":   pair.target_code,
            "source_url":    pair.source_url,
            "tokens_used":   pair.tokens_used,
            "provider":      pair.provider,
            "quality_score": pair.quality_score,
            "agent_ratings": pair.agent_ratings,
            "status":        pair.status,
        }
        result = self._db.table(self.TABLE).insert(row).execute()
        return result.data[0] if result.data else {}

    def update_status(self, pair_id_db: int, status: str) -> None:
        """Update the status of a row by its DB id."""
        self._db.table(self.TABLE).update({"status": status}).eq("id", pair_id_db).execute()

    # ── Read ──────────────────────────────────────────────────────────────────

    def fetch_accepted(self, pair_id: str, limit: int = 1000) -> list[dict]:
        """Fetch accepted training pairs for a language pair."""
        result = (
            self._db.table(self.TABLE)
            .select("source_code, target_code, quality_score")
            .eq("pair_id", pair_id)
            .eq("status", "accepted")
            .limit(limit)
            .execute()
        )
        return result.data or []

    def fetch_pending_review(self, limit: int = 50) -> list[dict]:
        """Fetch pairs awaiting human review."""
        result = (
            self._db.table(self.TABLE)
            .select("*")
            .eq("status", "review")
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data or []

    def stats(self) -> dict:
        """Return counts by status and pair_id."""
        result = self._db.table(self.TABLE).select("pair_id, status").execute()
        rows = result.data or []
        counts: dict[str, dict[str, int]] = {}
        for row in rows:
            pid = row["pair_id"]
            st = row["status"]
            counts.setdefault(pid, {})
            counts[pid][st] = counts[pid].get(st, 0) + 1
        return counts

    def difficult_patterns(self, threshold: float = 0.6, limit: int = 20) -> list[dict]:
        """
        Return accepted pairs with low quality_score – these represent
        'difficult' code patterns useful for targeted training.
        """
        result = (
            self._db.table(self.TABLE)
            .select("source_code, target_code, pair_id, quality_score")
            .eq("status", "accepted")
            .lt("quality_score", threshold)
            .order("quality_score", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data or []
