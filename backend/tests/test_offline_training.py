"""Tests for agent_evolution offline training from DB training_pairs."""
from __future__ import annotations
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile

from agent_evolution.rl_agent import RLAgent, ACTIONS, extract_state
from agent_evolution.train_from_data import (
    train_from_db,
    _infer_action,
    _pair_to_experience,
    DEFAULT_MIN_QUALITY,
)
from agent_evolution.trainer import train_combined
from training_data.dataset import DatasetManager


# ── _infer_action ─────────────────────────────────────────────────────────────

def test_infer_action_long_code_gives_v3():
    # ruby_len > 0.5 → v3_examples
    state = [0.8, 0.0, 0.0, 0.0, 0.0]
    assert ACTIONS[_infer_action(state)] == "v3_examples"


def test_infer_action_many_methods_gives_v3():
    state = [0.0, 0.5, 0.0, 0.0, 0.0]
    assert ACTIONS[_infer_action(state)] == "v3_examples"


def test_infer_action_loops_gives_v2():
    state = [0.1, 0.0, 0.0, 1.0, 0.0]
    assert ACTIONS[_infer_action(state)] == "v2_structured"


def test_infer_action_blocks_gives_v2():
    state = [0.1, 0.0, 0.0, 0.0, 1.0]
    assert ACTIONS[_infer_action(state)] == "v2_structured"


def test_infer_action_simple_gives_v1():
    state = [0.1, 0.0, 0.0, 0.0, 0.0]
    assert ACTIONS[_infer_action(state)] == "v1_minimal"


# ── _pair_to_experience ───────────────────────────────────────────────────────

def test_pair_to_experience_valid():
    row = {"source_code": "def hello\n  puts 'hi'\nend", "quality_score": 4.0}
    exp = _pair_to_experience(row)
    assert exp is not None
    state, action, reward, next_state, done = exp
    assert len(state) == 5
    assert action in range(len(ACTIONS))
    assert abs(reward - 4.0 / 5.0) < 1e-6
    assert done is True
    assert next_state == [0.0] * 5


def test_pair_to_experience_missing_source_returns_none():
    assert _pair_to_experience({"source_code": "", "quality_score": 4.0}) is None
    assert _pair_to_experience({"quality_score": 3.0}) is None


def test_pair_to_experience_null_quality_score():
    row = {"source_code": "puts 'hi'", "quality_score": None}
    exp = _pair_to_experience(row)
    assert exp is not None
    _, _, reward, _, _ = exp
    assert reward == 0.0


# ── train_from_db ─────────────────────────────────────────────────────────────

def _make_db_rows(n: int, quality: float = 4.0) -> list[dict]:
    return [
        {"source_code": f"def method_{i}\n  puts {i}\nend", "quality_score": quality}
        for i in range(n)
    ]


def test_train_from_db_pushes_experiences():
    with tempfile.TemporaryDirectory() as tmpdir:
        weights = Path(tmpdir) / "test_weights.pt"
        agent = RLAgent(weights_path=weights, epsilon=0.0)
        dm = MagicMock(spec=DatasetManager)
        dm.fetch_accepted.return_value = _make_db_rows(50, quality=4.0)

        result = train_from_db(agent, dataset_manager=dm, n_steps=10, verbose=False)

    assert result["experiences_pushed"] == 50
    assert result["rows_fetched"] == 50
    assert result["source"] == "db"


def test_train_from_db_quality_filter():
    with tempfile.TemporaryDirectory() as tmpdir:
        weights = Path(tmpdir) / "test_weights.pt"
        agent = RLAgent(weights_path=weights)
        dm = MagicMock(spec=DatasetManager)
        # 30 high quality + 20 low quality
        rows = _make_db_rows(30, quality=4.0) + _make_db_rows(20, quality=1.0)
        dm.fetch_accepted.return_value = rows

        result = train_from_db(
            agent, dataset_manager=dm, min_quality=3.0, n_steps=10, verbose=False
        )

    assert result["rows_fetched"] == 50
    assert result["rows_after_filter"] == 30
    assert result["experiences_pushed"] == 30


def test_train_from_db_runs_gradient_steps():
    with tempfile.TemporaryDirectory() as tmpdir:
        weights = Path(tmpdir) / "test_weights.pt"
        agent = RLAgent(weights_path=weights)
        dm = MagicMock(spec=DatasetManager)
        dm.fetch_accepted.return_value = _make_db_rows(100, quality=4.0)

        result = train_from_db(agent, dataset_manager=dm, n_steps=50, verbose=False)

    # With 100 experiences ≥ BATCH_SIZE (32), gradient steps should happen
    assert result["gradient_steps"] > 0
    assert result["final_loss"] is not None


def test_train_from_db_empty_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        weights = Path(tmpdir) / "test_weights.pt"
        agent = RLAgent(weights_path=weights)
        dm = MagicMock(spec=DatasetManager)
        dm.fetch_accepted.return_value = []

        result = train_from_db(agent, dataset_manager=dm, n_steps=50, verbose=False)

    assert result["experiences_pushed"] == 0
    assert result["gradient_steps"] == 0


def test_train_from_db_handles_db_error():
    with tempfile.TemporaryDirectory() as tmpdir:
        weights = Path(tmpdir) / "test_weights.pt"
        agent = RLAgent(weights_path=weights)
        dm = MagicMock(spec=DatasetManager)
        dm.fetch_accepted.side_effect = Exception("Connection refused")

        result = train_from_db(agent, dataset_manager=dm, verbose=False)

    assert "error" in result
    assert result["gradient_steps"] == 0


# ── train_combined ────────────────────────────────────────────────────────────

def test_train_combined_merges_results():
    from agent_swarm.memory import SwarmMemory

    with tempfile.TemporaryDirectory() as tmpdir:
        weights = Path(tmpdir) / "test_weights.pt"
        mem_path = Path(tmpdir) / "memory.json"
        agent = RLAgent(weights_path=weights)
        memory = SwarmMemory(path=mem_path)

        dm = MagicMock(spec=DatasetManager)
        dm.fetch_accepted.return_value = _make_db_rows(40, quality=4.0)

        result = train_combined(
            memory=memory,
            rl_agent=agent,
            dataset_manager=dm,
            n_steps_online=10,
            n_steps_offline=10,
            verbose=False,
        )

    assert "online" in result
    assert "offline" in result
    assert "total_gradient_steps" in result
    assert result["total_gradient_steps"] >= 0


# ── Endpoint ──────────────────────────────────────────────────────────────────

def test_train_offline_endpoint_requires_admin_key():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    resp = client.post("/evolution/train-offline", json={})
    assert resp.status_code in (403, 422)


def test_train_offline_endpoint_returns_stats():
    from fastapi.testclient import TestClient
    from app.main import app
    import app.main as main_module
    from unittest.mock import patch

    client = TestClient(app)
    mock_result = {
        "source": "db", "pair_id": "ruby->python",
        "rows_fetched": 10, "rows_after_filter": 10,
        "experiences_pushed": 10, "experiences_skipped": 0,
        "gradient_steps": 0, "final_loss": None,
        "epsilon": 1.0, "buffer_size": 10,
    }
    with patch.object(main_module, "ADMIN_API_KEY", "test_admin"), \
         patch("app.main.train_from_db", return_value=mock_result):
        resp = client.post(
            "/evolution/train-offline",
            json={"pair_id": "ruby->python", "n_steps": 10},
            headers={"X-Admin-Key": "test_admin"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "db"
    assert "experiences_pushed" in data
