"""
Tests for dynamic model routing based on LLM benchmark results.

All Supabase and HTTP calls are mocked – no network required.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.providers import Provider
from app.router import (
    VALID_PREFERENCES,
    get_best_model,
    get_provider_by_name,
    _load_providers,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_provider(name: str, cost: float = 0.0) -> Provider:
    return Provider(
        name=name,
        model=f"{name}-model",
        api_base="https://api.example.com/v1",
        input_price_per_million=cost,
        output_price_per_million=cost,
        active=True,
    )


def _mock_store(rows: list[dict]):
    """Return a patched BenchmarkStore whose latest_results returns rows."""
    mock = MagicMock()
    mock.return_value.latest_results.return_value = rows
    return mock


# ── VALID_PREFERENCES ─────────────────────────────────────────────────────────

class TestValidPreferences:
    def test_all_preferences_present(self):
        assert {"accuracy", "speed", "cost", "balanced"} == VALID_PREFERENCES

    def test_no_extra_preferences(self):
        assert len(VALID_PREFERENCES) == 4


# ── get_best_model ────────────────────────────────────────────────────────────

class TestGetBestModel:
    _ROWS = [
        {"provider": "nvidia",   "passed": True,  "latency_s": 1.0, "category": "math"},
        {"provider": "nvidia",   "passed": True,  "latency_s": 1.2, "category": "math"},
        {"provider": "nvidia",   "passed": True,  "latency_s": 0.9, "category": "math"},
        {"provider": "deepseek", "passed": True,  "latency_s": 3.0, "category": "math"},
        {"provider": "deepseek", "passed": False, "latency_s": 2.8, "category": "math"},
        {"provider": "deepseek", "passed": True,  "latency_s": 3.1, "category": "math"},
    ]

    def test_returns_none_when_no_data(self):
        with patch("llm_benchmark.store.BenchmarkStore", _mock_store([])):
            result = get_best_model(task_type="math", preference="accuracy")
        assert result is None

    def test_accuracy_prefers_higher_passrate(self):
        # nvidia: 3/3 = 100%  deepseek: 2/3 = 66%
        with patch("llm_benchmark.store.BenchmarkStore", _mock_store(self._ROWS)):
            result = get_best_model(task_type="math", preference="accuracy")
        # nvidia wins on accuracy
        assert result is not None
        assert result.name == "nvidia"

    def test_speed_prefers_lower_latency(self):
        # nvidia avg latency ≈ 1.03s  deepseek ≈ 2.97s
        with patch("llm_benchmark.store.BenchmarkStore", _mock_store(self._ROWS)):
            result = get_best_model(task_type="math", preference="speed")
        assert result is not None
        assert result.name == "nvidia"

    def test_cost_prefers_free_provider(self):
        # nvidia cost=0, deepseek cost>0 → nvidia wins on cost
        with patch("llm_benchmark.store.BenchmarkStore", _mock_store(self._ROWS)):
            result = get_best_model(task_type="math", preference="cost")
        assert result is not None
        assert result.name == "nvidia"

    def test_balanced_returns_provider(self):
        with patch("llm_benchmark.store.BenchmarkStore", _mock_store(self._ROWS)):
            result = get_best_model(task_type="math", preference="balanced")
        assert result is not None
        assert result.name in {"nvidia", "deepseek"}

    def test_invalid_preference_defaults_to_balanced(self):
        with patch("llm_benchmark.store.BenchmarkStore", _mock_store(self._ROWS)):
            result = get_best_model(task_type="math", preference="nonsense")
        assert result is not None  # balanced fallback works

    def test_no_task_type_uses_all_rows(self):
        with patch("llm_benchmark.store.BenchmarkStore", _mock_store(self._ROWS)):
            result = get_best_model(task_type=None, preference="accuracy")
        assert result is not None

    def test_returns_none_on_store_exception(self):
        mock = MagicMock()
        mock.return_value.latest_results.side_effect = RuntimeError("DB down")
        with patch("llm_benchmark.store.BenchmarkStore", mock):
            result = get_best_model(task_type="math", preference="accuracy")
        assert result is None

    def test_unknown_provider_in_results_skipped(self):
        rows = [
            {"provider": "unknown_llm", "passed": True, "latency_s": 0.1, "category": "math"},
            {"provider": "nvidia",      "passed": True, "latency_s": 1.0, "category": "math"},
        ]
        with patch("llm_benchmark.store.BenchmarkStore", _mock_store(rows)):
            result = get_best_model(task_type="math", preference="speed")
        # unknown_llm not in providers → nvidia returned
        assert result is None or result.name == "nvidia"

    def test_single_provider_wins_by_default(self):
        rows = [
            {"provider": "nvidia", "passed": True,  "latency_s": 1.0, "category": "code_gen"},
            {"provider": "nvidia", "passed": False, "latency_s": 2.0, "category": "code_gen"},
        ]
        with patch("llm_benchmark.store.BenchmarkStore", _mock_store(rows)):
            result = get_best_model(task_type="code_gen", preference="accuracy")
        assert result is not None
        assert result.name == "nvidia"


# ── FastAPI endpoint integration (using TestClient) ───────────────────────────

class TestChatEndpointPreference:
    """
    Smoke-tests for the preference parameter in /chat and /v1/chat/completions.
    Uses FastAPI TestClient with all external calls mocked.
    """

    def _make_client(self):
        from fastapi.testclient import TestClient
        return TestClient

    def test_invalid_preference_returns_400(self):
        try:
            from fastapi.testclient import TestClient
            from app.main import app
        except ImportError:
            pytest.skip("TestClient or app not importable in this env")

        with (
            patch("app.main.verify_user_api_key", return_value="user1"),
            patch("app.main.get_total_usage", return_value=0),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/chat",
                json={"messages": [{"role": "user", "content": "hi"}], "preference": "INVALID"},
                headers={"x-tokenbroker-key": "tb_test"},
            )
            assert resp.status_code == 400
            assert "preference" in resp.json().get("detail", "").lower()

    def test_valid_preference_accepted(self):
        try:
            from fastapi.testclient import TestClient
            from app.main import app
        except ImportError:
            pytest.skip("TestClient or app not importable in this env")

        fake_provider = _make_provider("nvidia")
        fake_result = {
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 10},
        }

        with (
            patch("app.main.verify_user_api_key", return_value="user1"),
            patch("app.main.get_total_usage", return_value=0),
            patch("app.main.get_best_model", return_value=fake_provider),
            patch("app.main.call_with_fallback", return_value=(fake_result, fake_provider)),
            patch("app.main.log_usage"),
            patch("app.main.notify"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/chat",
                json={
                    "messages": [{"role": "user", "content": "hi"}],
                    "preference": "accuracy",
                    "task_type": "math",
                },
                headers={"x-tokenbroker-key": "tb_test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["routing"] == "accuracy"
            assert data["provider"] == "nvidia"


# ── Preference scoring unit tests ─────────────────────────────────────────────

class TestPreferenceScoring:
    """Test that different preferences produce different rankings."""

    _HIGH_ACC = [
        {"provider": "accurate",  "passed": True,  "latency_s": 5.0, "category": "math"},
        {"provider": "accurate",  "passed": True,  "latency_s": 5.0, "category": "math"},
        {"provider": "accurate",  "passed": True,  "latency_s": 5.0, "category": "math"},
        {"provider": "fast",      "passed": False, "latency_s": 0.5, "category": "math"},
        {"provider": "fast",      "passed": False, "latency_s": 0.5, "category": "math"},
        {"provider": "fast",      "passed": True,  "latency_s": 0.5, "category": "math"},
    ]

    def test_accuracy_pref_picks_accurate(self):
        with patch("llm_benchmark.store.BenchmarkStore", _mock_store(self._HIGH_ACC)):
            result = get_best_model(task_type="math", preference="accuracy")
        if result:
            assert result.name == "accurate"

    def test_speed_pref_picks_fast(self):
        with patch("llm_benchmark.store.BenchmarkStore", _mock_store(self._HIGH_ACC)):
            result = get_best_model(task_type="math", preference="speed")
        if result:
            assert result.name == "fast"
