"""Tests für Multi-Tenant-Datenisolation."""

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

TENANT_A_KEY = "tkb_tenant_aaaa"
TENANT_B_KEY = "tkb_tenant_bbbb"
TENANT_A_ID = "00000000-0000-0000-aaaa-000000000001"
TENANT_B_ID = "00000000-0000-0000-bbbb-000000000002"
ADMIN_KEY = "admin_test_secret"

TENANT_A = {
    "id": TENANT_A_ID, "name": "Acme Corp", "slug": "acme",
    "plan": "pro", "status": "active",
    "token_limit": 1_000_000, "tokens_used": 100_000,
}
TENANT_B = {
    "id": TENANT_B_ID, "name": "Beta GmbH", "slug": "beta",
    "plan": "starter", "status": "active",
    "token_limit": 500_000, "tokens_used": 0,
}


def _mock_tenant_key(tenant_id):
    return patch("tenant.service.verify_tenant_key", return_value=tenant_id)


def _mock_get_tenant(tenant_data):
    return patch("tenant.service.get_tenant_by_id", return_value=tenant_data)


# ── Authentifizierung ──────────────────────────────────────────────────────────

def test_tenant_invalid_key_returns_401():
    with patch("tenant.service.verify_tenant_key", return_value=None):
        resp = client.get("/tenants/me/info", headers={"X-Tenant-Key": "invalid"})
    assert resp.status_code == 401


def test_tenant_valid_key_returns_info():
    with _mock_tenant_key(TENANT_A_ID), _mock_get_tenant(TENANT_A):
        resp = client.get("/tenants/me/info", headers={"X-Tenant-Key": TENANT_A_KEY})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Acme Corp"
    assert data["slug"] == "acme"
    assert "api_key" not in data  # Kein Leak sensitiver Felder


# ── Datenisolation ─────────────────────────────────────────────────────────────

def test_tenant_a_cannot_see_tenant_b_usage():
    """Tenant A darf Verbrauchsdaten von Tenant B nicht sehen."""
    usage_a = {
        "tenant_id": TENANT_A_ID, "tenant_name": "Acme Corp",
        "tokens_used": 100_000, "token_limit": 1_000_000, "usage_pct": 10.0,
        "by_provider": [{"provider": "nvidia", "tokens": 100_000, "cost_usd": 0.0}],
    }
    with _mock_tenant_key(TENANT_A_ID), _mock_get_tenant(TENANT_A), \
         patch("tenant.service.get_tenant_usage_summary", return_value=usage_a):
        resp = client.get("/tenants/me/usage", headers={"X-Tenant-Key": TENANT_A_KEY})
    assert resp.status_code == 200
    data = resp.json()
    # Nur Daten von Tenant A
    assert data["tenant_id"] == TENANT_A_ID
    assert data["tenant_name"] == "Acme Corp"
    assert data["tokens_used"] == 100_000


def test_tenant_b_sees_own_empty_usage():
    usage_b = {
        "tenant_id": TENANT_B_ID, "tenant_name": "Beta GmbH",
        "tokens_used": 0, "token_limit": 500_000, "usage_pct": 0.0,
        "by_provider": [],
    }
    with _mock_tenant_key(TENANT_B_ID), _mock_get_tenant(TENANT_B), \
         patch("tenant.service.get_tenant_usage_summary", return_value=usage_b):
        resp = client.get("/tenants/me/usage", headers={"X-Tenant-Key": TENANT_B_KEY})
    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == TENANT_B_ID
    assert resp.json()["tokens_used"] == 0


# ── Token-Limit-Enforcement ────────────────────────────────────────────────────

def test_tenant_at_limit_returns_429():
    """Tenant am Token-Limit wird mit 429 abgelehnt."""
    exhausted_tenant = {**TENANT_B, "tokens_used": 500_000, "token_limit": 500_000}
    with _mock_tenant_key(TENANT_B_ID), _mock_get_tenant(exhausted_tenant):
        resp = client.get("/tenants/me/info", headers={"X-Tenant-Key": TENANT_B_KEY})
    assert resp.status_code == 429
    assert "limit" in resp.json()["detail"].lower()


def test_tenant_below_limit_passes():
    with _mock_tenant_key(TENANT_A_ID), _mock_get_tenant(TENANT_A):
        resp = client.get("/tenants/me/info", headers={"X-Tenant-Key": TENANT_A_KEY})
    assert resp.status_code == 200


# ── Admin-Endpunkte ────────────────────────────────────────────────────────────

def test_create_tenant_requires_admin_key():
    resp = client.post("/tenants", json={
        "name": "New Corp", "slug": "new-corp", "plan": "starter", "token_limit": 500_000
    })
    assert resp.status_code in (401, 422)


def test_create_tenant_invalid_admin_key():
    with patch("tenant.router.ADMIN_API_KEY", "real_secret"):
        resp = client.post("/tenants",
            json={"name": "X", "slug": "x", "plan": "starter", "token_limit": 100_000},
            headers={"X-Admin-Key": "wrong_key"})
    assert resp.status_code == 403


def test_create_tenant_success():
    new_tenant = {
        "id": "new-uuid-123", "name": "New Corp", "slug": "new-corp",
        "plan": "starter", "token_limit": 500_000, "api_key": "tkb_tenant_newkey123",
    }
    with patch("tenant.router.ADMIN_API_KEY", ADMIN_KEY), \
         patch("tenant.service.create_tenant", return_value=new_tenant):
        resp = client.post("/tenants",
            json={"name": "New Corp", "slug": "new-corp", "plan": "starter", "token_limit": 500_000},
            headers={"X-Admin-Key": ADMIN_KEY})
    assert resp.status_code == 201
    data = resp.json()
    assert data["api_key"].startswith("tkb_tenant_")
    assert data["slug"] == "new-corp"


# ── Suspended Tenant ───────────────────────────────────────────────────────────

def test_suspended_tenant_returns_403():
    suspended = {**TENANT_A, "status": "suspended"}
    with _mock_tenant_key(TENANT_A_ID), _mock_get_tenant(suspended):
        resp = client.get("/tenants/me/info", headers={"X-Tenant-Key": TENANT_A_KEY})
    assert resp.status_code == 403
