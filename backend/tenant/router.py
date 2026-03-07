"""FastAPI-Router für Tenant-Endpunkte."""

from __future__ import annotations
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Depends

from .models import CreateTenantRequest, CreateTenantResponse
from .service import (
    verify_tenant_key,
    create_tenant,
    get_tenant_by_id,
    get_tenant_usage_summary,
)

router = APIRouter(prefix="/tenants", tags=["tenants"])

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")


def _require_admin(x_admin_key: str = Header(...)) -> None:
    if not ADMIN_API_KEY or x_admin_key != ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")


def require_tenant_key(x_tenant_key: str = Header(..., description="Tenant API key")) -> str:
    """FastAPI-Dependency: validiert Tenant-Key, gibt tenant_id zurück."""
    tenant_id = verify_tenant_key(x_tenant_key)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Invalid tenant key")
    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=403, detail="Tenant inactive or not found")
    # Token-Limit prüfen
    if tenant.get("tokens_used", 0) >= tenant.get("token_limit", 1_000_000):
        raise HTTPException(status_code=429, detail="Tenant token limit reached")
    return tenant_id


# ── Admin-Endpunkte ────────────────────────────────────────────────────────────

@router.post("", response_model=CreateTenantResponse, status_code=201)
def create_tenant_endpoint(
    req: CreateTenantRequest,
    _: None = Depends(_require_admin),
):
    """Neuen Tenant anlegen (Admin only)."""
    try:
        row = create_tenant(req.name, req.slug, req.plan, req.token_limit)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return CreateTenantResponse(
        id=row["id"],
        name=row["name"],
        slug=row["slug"],
        plan=row["plan"],
        token_limit=row["token_limit"],
        api_key=row["api_key"],
    )


@router.get("/{tenant_id}", dependencies=[Depends(_require_admin)])
def get_tenant_endpoint(tenant_id: str):
    """Tenant-Details abrufen (Admin only)."""
    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


# ── Tenant-eigene Endpunkte ────────────────────────────────────────────────────

@router.get("/me/usage")
def tenant_usage(tenant_id: str = Depends(require_tenant_key)):
    """Verbrauchsübersicht des eigenen Tenants."""
    return get_tenant_usage_summary(tenant_id)


@router.get("/me/info")
def tenant_info(tenant_id: str = Depends(require_tenant_key)):
    """Tenant-Profil (ohne sensible Felder)."""
    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {
        "id": tenant["id"],
        "name": tenant["name"],
        "slug": tenant["slug"],
        "plan": tenant["plan"],
        "status": tenant["status"],
        "token_limit": tenant["token_limit"],
        "tokens_used": tenant["tokens_used"],
    }
