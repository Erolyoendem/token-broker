"""Business-Logik für Tenant-Verwaltung und Datenisolation."""

from __future__ import annotations
import os
import secrets
from typing import Optional

from app.db import get_client


def _db():
    return get_client()


def verify_tenant_key(api_key: str) -> Optional[str]:
    """Prüft einen Tenant-API-Key. Gibt tenant_id zurück oder None."""
    result = (
        _db()
        .table("tenant_api_keys")
        .select("tenant_id")
        .eq("key", api_key)
        .eq("revoked", False)
        .maybe_single()
        .execute()
    )
    if not result.data:
        return None
    # last_used aktualisieren (fire-and-forget, Fehler ignorieren)
    try:
        from datetime import datetime, timezone
        _db().table("tenant_api_keys").update(
            {"last_used": datetime.now(timezone.utc).isoformat()}
        ).eq("key", api_key).execute()
    except Exception:
        pass
    return str(result.data["tenant_id"])


def get_tenant_by_id(tenant_id: str) -> Optional[dict]:
    """Gibt Tenant-Datensatz zurück oder None."""
    result = (
        _db()
        .table("tenants")
        .select("*")
        .eq("id", tenant_id)
        .eq("status", "active")
        .maybe_single()
        .execute()
    )
    return result.data or None


def create_tenant(name: str, slug: str, plan: str, token_limit: int) -> dict:
    """Legt neuen Tenant an und erstellt ersten API-Key."""
    row = (
        _db()
        .table("tenants")
        .insert({"name": name, "slug": slug, "plan": plan, "token_limit": token_limit})
        .execute()
        .data[0]
    )
    api_key = f"tkb_tenant_{secrets.token_urlsafe(32)}"
    _db().table("tenant_api_keys").insert(
        {"tenant_id": row["id"], "key": api_key, "label": "default"}
    ).execute()
    return {**row, "api_key": api_key}


def log_tenant_usage(
    tenant_id: str,
    provider: str,
    tokens_in: int,
    tokens_out: int,
    model: str = "",
    cost_usd: float = 0.0,
) -> None:
    """Schreibt Verbrauch in tenant_usage und inkrementiert tokens_used."""
    _db().table("tenant_usage").insert(
        {
            "tenant_id": tenant_id,
            "provider": provider,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
        }
    ).execute()
    # Gesamtverbrauch hochzählen
    total = tokens_in + tokens_out
    _db().rpc("increment_tenant_tokens", {"p_tenant_id": tenant_id, "p_delta": total}).execute()


def get_tenant_usage_summary(tenant_id: str) -> dict:
    """Aggregierter Verbrauch des Tenants."""
    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        return {}

    rows = (
        _db()
        .table("tenant_usage")
        .select("provider, tokens_in, tokens_out, cost_usd")
        .eq("tenant_id", tenant_id)
        .execute()
        .data
    ) or []

    by_provider: dict[str, dict] = {}
    for r in rows:
        p = r["provider"]
        if p not in by_provider:
            by_provider[p] = {"provider": p, "tokens": 0, "cost_usd": 0.0}
        by_provider[p]["tokens"] += r["tokens_in"] + r["tokens_out"]
        by_provider[p]["cost_usd"] += float(r["cost_usd"] or 0)

    used = tenant.get("tokens_used", 0)
    limit = tenant.get("token_limit", 1)
    return {
        "tenant_id": tenant_id,
        "tenant_name": tenant["name"],
        "tokens_used": used,
        "token_limit": limit,
        "usage_pct": round(used / limit * 100, 2) if limit else 0,
        "by_provider": list(by_provider.values()),
    }
