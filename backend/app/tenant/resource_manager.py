"""
Per-tenant resource limits and enforcement.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from fastapi import HTTPException
from app.db import get_client

DEFAULT_TOKEN_QUOTA = 1_000_000
DEFAULT_MAX_AGENTS = 5


@dataclass
class TenantLimits:
    tenant_id: str
    token_quota: int = DEFAULT_TOKEN_QUOTA
    max_agents: int = DEFAULT_MAX_AGENTS
    active_agents: int = 0


def get_tenant_limits(tenant_id: str) -> TenantLimits:
    """Load tenant settings from DB and return TenantLimits."""
    client = get_client()
    result = (
        client.table("tenants")
        .select("id, settings")
        .eq("id", tenant_id)
        .maybe_single()
        .execute()
    )
    settings = (result.data or {}).get("settings", {})
    return TenantLimits(
        tenant_id=tenant_id,
        token_quota=settings.get("token_quota", DEFAULT_TOKEN_QUOTA),
        max_agents=settings.get("max_agents", DEFAULT_MAX_AGENTS),
    )


def get_tenant_token_usage(tenant_id: str) -> int:
    """Sum of tokens used by all users within the tenant."""
    client = get_client()
    result = (
        client.table("token_usage")
        .select("tokens_used")
        .eq("tenant_id", tenant_id)
        .execute()
    )
    return sum(row["tokens_used"] for row in (result.data or []))


def enforce_token_quota(tenant_id: str) -> None:
    """Raise 429 if tenant has exceeded their token quota."""
    limits = get_tenant_limits(tenant_id)
    used = get_tenant_token_usage(tenant_id)
    if used >= limits.token_quota:
        raise HTTPException(
            status_code=429,
            detail=f"Tenant token quota exceeded ({used}/{limits.token_quota})",
        )


def enforce_agent_limit(tenant_id: str, current_agents: int) -> None:
    """Raise 429 if tenant would exceed max parallel agents."""
    limits = get_tenant_limits(tenant_id)
    if current_agents >= limits.max_agents:
        raise HTTPException(
            status_code=429,
            detail=f"Tenant agent limit reached ({current_agents}/{limits.max_agents})",
        )
