import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "TokenBroker"}


def test_list_providers():
    response = client.get("/providers")
    assert response.status_code == 200
    providers = response.json()
    assert len(providers) >= 2
    names = [p["name"] for p in providers]
    assert "nvidia" in names
    assert "deepseek" in names


def test_router_picks_cheapest():
    from app.router import get_cheapest_provider
    provider = get_cheapest_provider()
    # NVIDIA is free (0.0 cost), so it should be selected first
    assert provider.name == "nvidia"
