from unittest.mock import patch, MagicMock
from app.crowdfunding import create_group_buy, join_group_buy, check_and_trigger


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
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = row
    with patch("app.crowdfunding.get_client", return_value=client):
        result = check_and_trigger(1)
    assert result["status"] == "pending"
