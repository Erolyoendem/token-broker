"""
DeliveryResourceManager – Verwaltet Kontingente und Last pro Kunde.

Verfolgt:
  - Parallele Jobs pro Kunde (max_parallel_jobs)
  - Token-Budget pro Kunde und Monat
  - Reservierungen und Freigaben

Basiert konzeptuell auf backend/app/tenant/resource_manager.py,
ist aber auf Delivery-Jobs spezialisiert.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Defaults
DEFAULT_MAX_PARALLEL = 3
DEFAULT_MONTHLY_TOKEN_BUDGET = 10_000_000


@dataclass
class CustomerQuota:
    customer_id:     str
    max_parallel:    int   = DEFAULT_MAX_PARALLEL
    monthly_tokens:  int   = DEFAULT_MONTHLY_TOKEN_BUDGET
    tokens_used:     int   = 0
    active_jobs:     set   = field(default_factory=set)

    @property
    def parallel_count(self) -> int:
        return len(self.active_jobs)


class DeliveryResourceManager:
    """
    Thread-safe Kontingent-Manager für Delivery-Jobs.

    Kümmert sich um:
    - Parallele Job-Limits pro Kunde
    - Token-Budget-Tracking
    - Reservierung / Freigabe von Kapazität
    """

    def __init__(self) -> None:
        self._quotas: dict[str, CustomerQuota] = {}
        self._lock = threading.Lock()

    # ── Quota management ──────────────────────────────────────────────────────

    def get_quota(self, customer_id: str) -> CustomerQuota:
        with self._lock:
            if customer_id not in self._quotas:
                # Try to load from DB; fall back to defaults
                quota = self._load_from_db(customer_id)
                self._quotas[customer_id] = quota
            return self._quotas[customer_id]

    def _load_from_db(self, customer_id: str) -> CustomerQuota:
        try:
            from app.db import get_client
            row = (
                get_client()
                .table("tenants")
                .select("id, settings")
                .eq("id", customer_id)
                .maybe_single()
                .execute()
                .data
            )
            if row:
                settings = (row.get("settings") or {})
                return CustomerQuota(
                    customer_id=customer_id,
                    max_parallel=settings.get("max_parallel_jobs", DEFAULT_MAX_PARALLEL),
                    monthly_tokens=settings.get("token_quota", DEFAULT_MONTHLY_TOKEN_BUDGET),
                )
        except Exception as exc:
            log.debug("Could not load quota from DB: %s", exc)
        return CustomerQuota(customer_id=customer_id)

    # ── Reserve / Release ─────────────────────────────────────────────────────

    def check_quota(self, customer_id: str) -> tuple[bool, str]:
        """Returns (ok, reason). ok=True means job can proceed."""
        quota = self.get_quota(customer_id)
        if quota.parallel_count >= quota.max_parallel:
            return False, (
                f"Max parallel jobs reached ({quota.parallel_count}/{quota.max_parallel})"
            )
        if quota.tokens_used >= quota.monthly_tokens:
            return False, (
                f"Monthly token budget exhausted ({quota.tokens_used}/{quota.monthly_tokens})"
            )
        return True, "ok"

    def reserve(self, customer_id: str, job_id: str) -> None:
        quota = self.get_quota(customer_id)
        with self._lock:
            quota.active_jobs.add(job_id)
        log.debug("Reserved slot for customer=%s job=%s (active=%d)",
                  customer_id[:8], job_id[:8], quota.parallel_count)

    def release(self, customer_id: str, job_id: str) -> None:
        quota = self.get_quota(customer_id)
        with self._lock:
            quota.active_jobs.discard(job_id)
        log.debug("Released slot for customer=%s job=%s (active=%d)",
                  customer_id[:8], job_id[:8], quota.parallel_count)

    def record_tokens(self, customer_id: str, tokens: int) -> None:
        quota = self.get_quota(customer_id)
        with self._lock:
            quota.tokens_used += tokens

    # ── Stats ─────────────────────────────────────────────────────────────────

    def usage_summary(self, customer_id: str) -> dict:
        quota = self.get_quota(customer_id)
        return {
            "customer_id":      customer_id,
            "active_jobs":      list(quota.active_jobs),
            "parallel_count":   quota.parallel_count,
            "max_parallel":     quota.max_parallel,
            "tokens_used":      quota.tokens_used,
            "monthly_tokens":   quota.monthly_tokens,
            "budget_pct":       round(
                quota.tokens_used / quota.monthly_tokens * 100, 1
            ) if quota.monthly_tokens else 0,
        }
