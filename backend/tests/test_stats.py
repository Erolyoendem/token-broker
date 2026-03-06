from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import os

os.environ.setdefault("ADMIN_API_KEY", "test_admin_key")

from app.main import app
from app import metrics

client = TestClient(app)
ADMIN = {"X-Admin-Key": "test_admin_key"}


def _mock_db_client(token_rows=None, group_buy_rows=None):
    db = MagicMock()
    # token_usage query chain
    token_chain = db.table("token_usage").select("provider, tokens_used, timestamp").gte("timestamp", MagicMock())
    token_chain.execute.return_value.data = token_rows or []
    db.table.return_value.select.return_value.gte.return_value.execute.return_value.data = token_rows or []
    # group_buys query chain
    db.table.return_value.select.return_value.execute.return_value.data = group_buy_rows or []
    return db


# ── /stats/token-usage ───────────────────────────────────────────────────────

def test_token_usage_requires_admin():
    resp = client.get("/stats/token-usage")
    assert resp.status_code == 422  # missing header

    resp = client.get("/stats/token-usage", headers={"X-Admin-Key": "wrong"})
    assert resp.status_code == 403


def test_token_usage_returns_data():
    rows = [
        {"provider": "nvidia",   "tokens_used": 3000, "timestamp": "2026-03-07T10:00:00+00:00"},
        {"provider": "deepseek", "tokens_used": 1000, "timestamp": "2026-03-07T11:00:00+00:00"},
        {"provider": "nvidia",   "tokens_used": 2000, "timestamp": "2026-03-07T12:00:00+00:00"},
    ]
    with patch("app.main.get_client") as mock_get_client:
        db = MagicMock()
        db.table.return_value.select.return_value.gte.return_value.execute.return_value.data = rows
        mock_get_client.return_value = db
        resp = client.get("/stats/token-usage", headers=ADMIN)

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_tokens"] == 6000
    by_p = {e["provider"]: e["tokens"] for e in data["by_provider"]}
    assert by_p["nvidia"] == 5000
    assert by_p["deepseek"] == 1000


def test_token_usage_empty():
    with patch("app.main.get_client") as mock_get_client:
        db = MagicMock()
        db.table.return_value.select.return_value.gte.return_value.execute.return_value.data = []
        mock_get_client.return_value = db
        resp = client.get("/stats/token-usage", headers=ADMIN)

    assert resp.status_code == 200
    assert resp.json()["total_tokens"] == 0
    assert resp.json()["by_provider"] == []


# ── /stats/group-buys ────────────────────────────────────────────────────────

def test_group_buys_requires_admin():
    resp = client.get("/stats/group-buys", headers={"X-Admin-Key": "bad"})
    assert resp.status_code == 403


def test_group_buys_returns_counts():
    rows = [
        {"status": "pending"},
        {"status": "pending"},
        {"status": "active"},
        {"status": "completed"},
    ]
    with patch("app.main.get_client") as mock_get_client:
        db = MagicMock()
        db.table.return_value.select.return_value.execute.return_value.data = rows
        mock_get_client.return_value = db
        resp = client.get("/stats/group-buys", headers=ADMIN)

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 4
    by_status = {e["status"]: e["count"] for e in data["by_status"]}
    assert by_status["pending"] == 2
    assert by_status["active"] == 1
    assert by_status["completed"] == 1


# ── /stats/errors ────────────────────────────────────────────────────────────

def test_errors_requires_admin():
    resp = client.get("/stats/errors", headers={"X-Admin-Key": "nope"})
    assert resp.status_code == 403


def test_errors_returns_rates():
    metrics.reset()
    metrics.record_request("/chat", 200)
    metrics.record_request("/chat", 200)
    metrics.record_request("/chat", 500)
    metrics.record_request("/health", 200)

    resp = client.get("/stats/errors", headers=ADMIN)
    assert resp.status_code == 200
    endpoints = {e["endpoint"]: e for e in resp.json()["endpoints"]}

    assert endpoints["/chat"]["requests"] == 3
    assert endpoints["/chat"]["errors"] == 1
    assert abs(endpoints["/chat"]["error_rate"] - 33.3) < 0.1
    assert endpoints["/health"]["errors"] == 0

    metrics.reset()
