from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
AUTH = {"X-Api-Key": "tkb_test_123"}
USER_ID = "00000000-0000-0000-0000-000000000001"


def _mock_auth():
    return patch("app.auth.verify_user_api_key", return_value=USER_ID)


def test_create_group_buy():
    created = {"id": 1, "name": "DeepSeek Bulk", "status": "pending",
               "target_tokens": 1000000, "current_tokens": 0,
               "price_per_token": 0.001, "provider": "deepseek"}
    with _mock_auth(), \
         patch("app.crowdfunding.get_client") as mc:
        mc.return_value.table.return_value.insert.return_value.execute.return_value.data = [created]
        resp = client.post("/group-buys", json={
            "name": "DeepSeek Bulk", "target_tokens": 1000000,
            "price_per_token": 0.001, "provider": "deepseek",
        }, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["id"] == 1
    assert resp.json()["status"] == "pending"


def test_join_group_buy():
    joined = {"id": 1, "current_tokens": 700000, "status": "pending", "target_tokens": 1000000}
    triggered = {**joined}
    with _mock_auth(), \
         patch("app.main.join_group_buy", return_value=joined), \
         patch("app.main.check_and_trigger", return_value=triggered):
        resp = client.post("/group-buys/1/join", json={"tokens": 200000}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["current_tokens"] == 700000


def test_list_group_buys():
    rows = [{"id": 1, "name": "Test", "status": "pending", "current_tokens": 0,
             "target_tokens": 1000000, "provider": "deepseek"}]
    with _mock_auth(), \
         patch("app.main.get_client") as mc:
        mc.return_value.table.return_value.select.return_value.in_.return_value.execute.return_value.data = rows
        resp = client.get("/group-buys", headers=AUTH)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
