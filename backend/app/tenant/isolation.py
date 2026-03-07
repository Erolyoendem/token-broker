"""
Tenant isolation middleware.
Resolves tenant_id from the incoming API key and attaches it to request.state.
"""
from __future__ import annotations
from typing import Optional, Tuple
from fastapi import HTTPException
from app.db import get_client


def resolve_tenant(api_key: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Look up api_key in api_keys table (joined with tenants).
    Returns (user_id, tenant_id). tenant_id may be None for legacy keys.
    """
    client = get_client()
    result = (
        client.table("api_keys")
        .select("user_id, tenant_id")
        .eq("key", api_key)
        .maybe_single()
        .execute()
    )
    if not result.data:
        return None, None
    return str(result.data["user_id"]), result.data.get("tenant_id")


def assert_tenant_owns_resource(resource_tenant_id: Optional[str], caller_tenant_id: Optional[str]) -> None:
    """Raise 403 if resource belongs to a different tenant."""
    if resource_tenant_id and caller_tenant_id and resource_tenant_id != caller_tenant_id:
        raise HTTPException(status_code=403, detail="Cross-tenant access denied")


def verify_master_api_key(x_api_key: str) -> Tuple[str, str]:
    """
    Validates a tenant master key against the tenants table.
    Returns (tenant_id, tenant_name). Raises 401 if invalid.
    """
    client = get_client()
    result = (
        client.table("tenants")
        .select("id, name")
        .eq("api_key", x_api_key)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=401, detail="Invalid tenant master key")
    return result.data["id"], result.data["name"]
