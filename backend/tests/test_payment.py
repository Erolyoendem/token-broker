from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
AUTH = {"X-Api-Key": "tkb_test_123"}
USER_ID = "00000000-0000-0000-0000-000000000001"


def _mock_auth():
    return patch("app.auth.verify_user_api_key", return_value=USER_ID)


def test_payment_config_public():
    """GET /payment/config is public (no auth required)."""
    with patch("app.main.get_publishable_key", return_value="pk_test_abc"):
        resp = client.get("/payment/config")
    assert resp.status_code == 200
    assert resp.json()["publishable_key"] == "pk_test_abc"


def test_create_intent_returns_client_secret():
    intent_result = {
        "client_secret": "pi_test_secret_123",
        "amount": 1000,
        "currency": "eur",
        "payment_intent_id": "pi_test_123",
    }
    with _mock_auth(), \
         patch("app.main.join_group_buy", return_value={"id": 1, "current_tokens": 100}), \
         patch("app.main.create_payment_intent", return_value=intent_result):
        resp = client.post("/payment/create-intent",
                           json={"group_buy_id": 1, "tokens": 100_000},
                           headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["client_secret"] == "pi_test_secret_123"
    assert resp.json()["amount"] == 1000


def test_create_intent_group_buy_not_found():
    with _mock_auth(), \
         patch("app.main.join_group_buy", return_value={"id": 1, "current_tokens": 0}), \
         patch("app.main.create_payment_intent", side_effect=ValueError("Group buy 99 not found")):
        resp = client.post("/payment/create-intent",
                           json={"group_buy_id": 99, "tokens": 1000},
                           headers=AUTH)
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_create_intent_requires_auth():
    resp = client.post("/payment/create-intent",
                       json={"group_buy_id": 1, "tokens": 1000})
    assert resp.status_code in (401, 422)


def test_payment_amount_calculation():
    """Unit test: tokens * price_per_token → correct cents."""
    from unittest.mock import MagicMock
    import stripe

    gb_data = {"price_per_token": 0.001, "provider": "deepseek"}
    mock_intent = MagicMock()
    mock_intent.id = "pi_xyz"
    mock_intent.client_secret = "secret_xyz"
    mock_intent.status = "requires_payment_method"

    db_client = MagicMock()
    db_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = gb_data
    db_client.table.return_value.insert.return_value.execute.return_value.data = [{}]

    with patch("app.payment.get_client", return_value=db_client), \
         patch("app.payment.stripe.PaymentIntent.create", return_value=mock_intent) as mock_create:
        from app.payment import create_payment_intent
        result = create_payment_intent(1, USER_ID, 500_000)

    # 500_000 tokens * 0.001 EUR = 500 EUR = 50_000 cents
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args[1]
    assert call_kwargs["amount"] == 50_000
    assert call_kwargs["currency"] == "eur"
    assert result["client_secret"] == "secret_xyz"
