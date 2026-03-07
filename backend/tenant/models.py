"""Pydantic-Modelle für die Multi-Tenant-Architektur."""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class Tenant(BaseModel):
    id: str
    name: str
    slug: str
    plan: str = "starter"
    status: str = "active"
    token_limit: int = 1_000_000
    tokens_used: int = 0
    metadata: dict = {}


class TenantApiKey(BaseModel):
    id: str
    tenant_id: str
    key: str
    label: Optional[str] = None
    revoked: bool = False


class TenantUsage(BaseModel):
    tenant_id: str
    provider: str
    model: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


# ── Request/Response-Schemata ──────────────────────────────────────────────────

class CreateTenantRequest(BaseModel):
    name: str
    slug: str
    plan: str = "starter"
    token_limit: int = 1_000_000


class CreateTenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    plan: str
    token_limit: int
    api_key: str       # erster API-Key des neuen Tenants


class TenantUsageSummary(BaseModel):
    tenant_id: str
    tenant_name: str
    tokens_used: int
    token_limit: int
    usage_pct: float
    by_provider: list[dict]
