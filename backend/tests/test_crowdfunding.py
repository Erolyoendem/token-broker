from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.crowdfunding import create_group_buy, join_group_buy, check_and_trigger

client = TestClient(app)
AUTH = {"X-Api-Key": "tkb_test_123"}
USER_ID = "00000000-0000-0000-0000-000000000001"


def _mock_client(insert_data=None, select_data=None, update_data=None):
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.return_value.data = [insert_data or {}]
    client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = select_data or {}
    client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [update_data or {}]
    return client


def test_create_group_buy_returns_row():
    expected = {"id": 1, "name": "Test Buy", "status": "pending"}
    with patch("app.crowdfunding.get_client", return_value=_mock_client(insert_data=expected)):
        result = create_group_buy("Test Buy", 1_000_000, 0.001, "deepseek")
    assert result["name"] == "Test Buy"
    assert result["status"] == "pending"


def test_join_group_buy_updates_tokens():
    select_data = {"current_tokens": 500_000}
    update_data = {"id": 1, "current_tokens": 700_000}
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.return_value.data = [{}]
    client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = select_data
    client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [update_data]
    with patch("app.crowdfunding.get_client", return_value=client):
        result = join_group_buy(1, "00000000-0000-0000-0000-000000000001", 200_000)
    assert result["current_tokens"] == 700_000


def test_check_and_trigger_activates_when_target_reached():
    row = {"id": 1, "status": "pending", "current_tokens": 1_000_000, "target_tokens": 1_000_000}
    activated = {**row, "status": "active"}
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = row
    client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [activated]
    with patch("app.crowdfunding.get_client", return_value=client):
        result = check_and_trigger(1)
    assert result["status"] == "active"


def test_check_and_trigger_stays_pending_when_target_not_reached():
    row = {"id": 1, "status": "pending", "current_tokens": 500_000, "target_tokens": 1_000_000}
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = row
    with patch("app.crowdfunding.get_client", return_value=mock_client):
        result = check_and_trigger(1)
    assert result["status"] == "pending"


def test_create_group_buy_endpoint_valid_provider():
    created_row = {"id": 42, "name": "Test Buy", "status": "pending"}
    with patch("app.auth.verify_user_api_key", return_value=USER_ID), \
         patch("app.main.get_provider_by_name", return_value=MagicMock(name="nvidia")), \
         patch("app.main.create_group_buy", return_value=created_row):
        resp = client.post(
            "/group-buys",
            json={"name": "Test Buy", "target_tokens": 1_000_000,
                  "price_per_token": 0.01, "provider": "nvidia"},
            headers=AUTH,
        )
    assert resp.status_code == 200
    assert resp.json()["id"] == 42
    assert resp.json()["status"] == "pending"


def test_create_group_buy_endpoint_invalid_provider():
    with patch("app.auth.verify_user_api_key", return_value=USER_ID), \
         patch("app.main.get_provider_by_name", side_effect=ValueError("Unknown provider: unknown")):
        resp = client.post(
            "/group-buys",
            json={"name": "Test Buy", "target_tokens": 1_000_000,
                  "price_per_token": 0.01, "provider": "unknown"},
            headers=AUTH,
        )
    assert resp.status_code == 400
    assert "Unknown provider" in resp.json()["detail"]
