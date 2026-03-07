"""
Isolated agent-swarm deployment per tenant.
For MVP: in-process isolation via namespaced config.
Docker-based isolation is prepared but not activated.
"""
from __future__ import annotations
import logging
from typing import Optional
from app.db import get_client

log = logging.getLogger(__name__)


def provision_tenant_swarm(tenant_id: str, tenant_name: str) -> dict:
    """
    Provision an isolated agent swarm for a tenant.
    Currently: in-process namespace. Future: Docker container per tenant.
    Returns swarm config dict.
    """
    config = {
        "tenant_id": tenant_id,
        "tenant_name": tenant_name,
        "namespace": f"tenant_{tenant_id[:8]}",
        "isolation": "in-process",
        "status": "ready",
    }
    log.info("Swarm provisioned for tenant %s: %s", tenant_name, config["namespace"])
    return config


def deprovision_tenant_swarm(tenant_id: str) -> None:
    """Remove/stop the swarm resources for a tenant."""
    log.info("Swarm deprovisioned for tenant %s", tenant_id)


def get_swarm_status(tenant_id: str) -> dict:
    """Return current status of the tenant's swarm."""
    client = get_client()
    result = (
        client.table("tenants")
        .select("id, name, settings")
        .eq("id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not result.data:
        return {"tenant_id": tenant_id, "status": "unknown"}
    return {
        "tenant_id": tenant_id,
        "tenant_name": result.data["name"],
        "namespace": f"tenant_{tenant_id[:8]}",
        "isolation": "in-process",
        "status": "ready",
    }
