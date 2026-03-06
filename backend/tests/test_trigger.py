from unittest.mock import patch, MagicMock
from app.trigger import process_completed_group_buys


def _make_row(id, status, current_tokens, target_tokens, **kwargs):
    return {
        "id": id,
        "status": status,
        "current_tokens": current_tokens,
        "target_tokens": target_tokens,
        "name": f"group-buy-{id}",
        "provider": "nvidia",
        **kwargs,
    }


def test_triggers_when_target_reached():
    pending_row = _make_row(1, "pending", current_tokens=1000, target_tokens=1000)
    activated_row = {**pending_row, "status": "active"}

    mock_client = MagicMock()
    (mock_client.table.return_value
     .select.return_value.eq.return_value.execute.return_value.data) = [pending_row]
    (mock_client.table.return_value
     .update.return_value.eq.return_value.execute.return_value.data) = [activated_row]

    with patch("app.trigger.get_client", return_value=mock_client):
        result = process_completed_group_buys()

    assert len(result) == 1
    assert result[0]["status"] == "active"


def test_skips_when_target_not_reached():
    pending_row = _make_row(2, "pending", current_tokens=500, target_tokens=1000)

    mock_client = MagicMock()
    (mock_client.table.return_value
     .select.return_value.eq.return_value.execute.return_value.data) = [pending_row]

    with patch("app.trigger.get_client", return_value=mock_client):
        result = process_completed_group_buys()

    assert result == []
    mock_client.table.return_value.update.assert_not_called()


def test_handles_multiple_rows_selectively():
    rows = [
        _make_row(3, "pending", current_tokens=2000, target_tokens=1000),
        _make_row(4, "pending", current_tokens=300, target_tokens=1000),
    ]
    activated = {**rows[0], "status": "active"}

    mock_client = MagicMock()
    select_chain = mock_client.table.return_value.select.return_value.eq.return_value
    select_chain.execute.return_value.data = rows
    (mock_client.table.return_value
     .update.return_value.eq.return_value.execute.return_value.data) = [activated]

    with patch("app.trigger.get_client", return_value=mock_client):
        result = process_completed_group_buys()

    assert len(result) == 1
    assert result[0]["id"] == 3
