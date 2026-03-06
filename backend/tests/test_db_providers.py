from unittest.mock import patch
from app.db_providers import get_active_providers_from_db
from app.providers import Provider

MOCK_ROWS = [
    {"name": "nvidia", "model": "meta/llama-3.1-70b-instruct",
     "api_base": "https://integrate.api.nvidia.com/v1",
     "input_price_per_million": 0, "output_price_per_million": 0,
     "cache_discount": 0, "active": True},
    {"name": "deepseek", "model": "deepseek-chat",
     "api_base": "https://api.deepseek.com/v1",
     "input_price_per_million": 0.24, "output_price_per_million": 0.36,
     "cache_discount": 0.1, "active": True},
]


def _mock_client(rows):
    class FakeExec:
        data = rows
    class FakeQuery:
        def eq(self, *a): return self
        def execute(self): return FakeExec()
    class FakeTable:
        def select(self, *a): return FakeQuery()
    class FakeClient:
        def table(self, *a): return FakeTable()
    return FakeClient()


def test_returns_at_least_two_providers():
    with patch("app.db_providers.get_client", return_value=_mock_client(MOCK_ROWS)):
        providers = get_active_providers_from_db()
    assert len(providers) >= 2


def test_returns_provider_instances():
    with patch("app.db_providers.get_client", return_value=_mock_client(MOCK_ROWS)):
        providers = get_active_providers_from_db()
    assert all(isinstance(p, Provider) for p in providers)


def test_names_correct():
    with patch("app.db_providers.get_client", return_value=_mock_client(MOCK_ROWS)):
        providers = get_active_providers_from_db()
    names = {p.name for p in providers}
    assert "nvidia" in names and "deepseek" in names
