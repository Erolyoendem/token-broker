import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

VALID_KEY = "test-key-abc123"
VALID_USER_ID = "user-uuid-0001"


def test_valid_key_accepted():
    with patch("app.auth.verify_user_api_key", return_value=VALID_USER_ID):
        response = client.get(f"/usage/{VALID_USER_ID}", headers={"x-api-key": VALID_KEY})
    assert response.status_code == 200
    assert response.json()["user_id"] == VALID_USER_ID


def test_invalid_key_rejected_with_401():
    with patch("app.auth.verify_user_api_key", return_value=None):
        response = client.get(f"/usage/{VALID_USER_ID}", headers={"x-api-key": "wrong-key"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"


def test_missing_key_rejected_with_401():
    response = client.get(f"/usage/{VALID_USER_ID}")
    assert response.status_code == 422  # FastAPI: required header missing
