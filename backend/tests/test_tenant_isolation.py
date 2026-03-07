"""Tests für Multi-Tenant-Isolation, Ressourcenlimits und API-Key-Berechtigungen."""
from unittest.mock import patch, MagicMock, call
from fastapi.testclient import TestClient
from fastapi import HTTPException
import pytest
from app.main import app
from app.tenant.isolation import resolve_tenant, assert_tenant_owns_resource
from app.tenant.resource_manager import enforce_token_quota, enforce_agent_limit

client = TestClient(app)

TENANT_A = "aaaaaaaa-0000-0000-0000-000000000001"
TENANT_B = "bbbbbbbb-0000-0000-0000-000000000002"
USER_A   = "00000000-0000-0000-0000-000000000001"


# ── Isolation: resolve_tenant ──────────────────────────────────────────────

def test_resolve_tenant_returns_correct_ids():
    mc = MagicMock()
    mc.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
        "user_id": USER_A, "tenant_id": TENANT_A
    }
    with patch("app.tenant.isolation.get_client", return_value=mc):
        user_id, tenant_id = resolve_tenant("valid-key")
    assert user_id == USER_A
    assert tenant_id == TENANT_A


def test_resolve_tenant_returns_none_for_invalid_key():
    mc = MagicMock()
    mc.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None
    with patch("app.tenant.isolation.get_client", return_value=mc):
        user_id, tenant_id = resolve_tenant("bad-key")
    assert user_id is None
    assert tenant_id is None


# ── Isolation: cross-tenant access ────────────────────────────────────────

def test_cross_tenant_access_denied():
    with pytest.raises(HTTPException) as exc:
        assert_tenant_owns_resource(TENANT_A, TENANT_B)
    assert exc.value.status_code == 403


def test_same_tenant_access_allowed():
    assert_tenant_owns_resource(TENANT_A, TENANT_A)  # must not raise


def test_no_tenant_context_is_allowed():
    assert_tenant_owns_resource(None, None)  # legacy keys: must not raise


# ── Resource limits ────────────────────────────────────────────────────────

def _patch_limits(quota, used_total):
    """Returns (limits_mock, usage_mock) for resource_manager patches."""
    limits_mc = MagicMock()
    limits_mc.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
        "settings": {"token_quota": quota, "max_agents": 3}
    }
    usage_rows = [{"tokens_used": used_total}]
    limits_mc.table.return_value.select.return_value.eq.return_value.execute.return_value.data = usage_rows
    return limits_mc


def test_enforce_token_quota_blocks_when_exceeded():
    mc = _patch_limits(quota=1_000_000, used_total=1_100_000)
    with patch("app.tenant.resource_manager.get_client", return_value=mc):
        with pytest.raises(HTTPException) as exc:
            enforce_token_quota(TENANT_A)
    assert exc.value.status_code == 429


def test_enforce_token_quota_passes_when_under_limit():
    mc = _patch_limits(quota=1_000_000, used_total=100_000)
    with patch("app.tenant.resource_manager.get_client", return_value=mc):
        enforce_token_quota(TENANT_A)  # must not raise


def test_enforce_agent_limit_blocks_at_max():
    mc = _patch_limits(quota=1_000_000, used_total=0)
    with patch("app.tenant.resource_manager.get_client", return_value=mc):
        with pytest.raises(HTTPException) as exc:
            enforce_agent_limit(TENANT_A, current_agents=3)
    assert exc.value.status_code == 429


def test_enforce_agent_limit_passes_below_max():
    mc = _patch_limits(quota=1_000_000, used_total=0)
    with patch("app.tenant.resource_manager.get_client", return_value=mc):
        enforce_agent_limit(TENANT_A, current_agents=2)  # must not raise


# ── Tenant API endpoint ─────────────────────────────────────────────────────

def test_create_tenant_endpoint_requires_admin_key():
    """Without x-admin-key the endpoint must reject the request."""
    resp = client.post("/tenants", json={"name": "Acme", "slug": "acme"})
    assert resp.status_code == 422  # required header missing


def test_create_tenant_endpoint_rejects_bad_admin_key():
    import os
    with patch.dict(os.environ, {"ADMIN_API_KEY": "secret"}):
        resp = client.post(
            "/tenants",
            json={"name": "Acme", "slug": "acme"},
            headers={"x-admin-key": "wrong"},
        )
    assert resp.status_code == 403


def test_tenant_me_info_rejects_invalid_key():
    """Invalid tenant key must return 401."""
    mc = MagicMock()
    mc.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None
    with patch("tenant.service.get_client", return_value=mc):
        resp = client.get("/tenants/me/info", headers={"x-tenant-key": "invalid"})
    assert resp.status_code == 401
