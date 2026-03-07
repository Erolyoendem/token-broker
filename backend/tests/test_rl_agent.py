"""
Tests for agent_evolution.rl_agent and agent_evolution.trainer.

Covers:
  - State extraction (feature engineering)
  - Action / state space dimensions
  - RLAgent: greedy vs epsilon selection, Q-values, save/load
  - ReplayBuffer: push, sample, capacity
  - DQN training loop with synthetic data
  - Trainer: experience loading from SwarmMemory, gradient steps
  - Orchestrator RL integration hook
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import torch

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_evolution.rl_agent import (
    RLAgent,
    ReplayBuffer,
    ACTIONS,
    N_ACTIONS,
    STATE_DIM,
    BATCH_SIZE,
    extract_state,
)
from agent_evolution.trainer import train_from_memory, _record_to_experience
from agent_swarm.memory import SwarmMemory

# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_RUBY = """\
class Calculator
  def add(a, b); a + b; end
  def multiply(a, b); a * b; end
end
"""

LOOP_RUBY = """\
[1, 2, 3].each do |n|
  puts n
end
"""


@pytest.fixture
def tmp_weights(tmp_path):
    return tmp_path / "weights.pt"


@pytest.fixture
def agent(tmp_weights):
    return RLAgent(weights_path=tmp_weights, epsilon=0.0)


@pytest.fixture
def tmp_memory(tmp_path):
    return SwarmMemory(path=tmp_path / "mem.json")


# ── State extraction ──────────────────────────────────────────────────────────

def test_extract_state_dimensions():
    state = extract_state(SAMPLE_RUBY)
    assert len(state) == STATE_DIM
    assert all(0.0 <= v <= 1.0 for v in state), "All features must be in [0, 1]"


def test_extract_state_detects_methods():
    state = extract_state(SAMPLE_RUBY)
    # has 2 `def ` → num_methods = 2/20 = 0.1
    assert state[1] == pytest.approx(2 / 20.0)


def test_extract_state_detects_classes():
    state = extract_state(SAMPLE_RUBY)
    # has 1 `class ` → num_classes = 1/10 = 0.1
    assert state[2] == pytest.approx(1 / 10.0)


def test_extract_state_detects_loops():
    state_no_loop = extract_state(SAMPLE_RUBY)
    state_loop    = extract_state(LOOP_RUBY)
    assert state_no_loop[3] == 0.0
    assert state_loop[3] == 1.0


def test_extract_state_detects_blocks():
    state_block    = extract_state(LOOP_RUBY)
    state_no_block = extract_state(SAMPLE_RUBY)
    assert state_block[4] == 1.0
    assert state_no_block[4] == 0.0


def test_extract_state_long_code_clamped():
    long_ruby = "x = 1\n" * 10_000
    state = extract_state(long_ruby)
    assert state[0] == pytest.approx(1.0)   # clamped at 1.0


# ── Action space ──────────────────────────────────────────────────────────────

def test_action_count():
    assert N_ACTIONS == 3
    assert len(ACTIONS) == N_ACTIONS


def test_actions_are_known_variants():
    from agent_swarm.generation_agent import PROMPT_VARIANTS
    for a in ACTIONS:
        assert a in PROMPT_VARIANTS, f"Action '{a}' not in PROMPT_VARIANTS"


# ── RLAgent: Q-network ────────────────────────────────────────────────────────

def test_rl_agent_select_action_greedy(agent):
    state = extract_state(SAMPLE_RUBY)
    action = agent.select_action(state, greedy=True)
    assert 0 <= action < N_ACTIONS


def test_rl_agent_select_action_shape(agent):
    """Greedy selection must return a valid action index for any input."""
    for _ in range(20):
        state = [float(i % 2) for i in range(STATE_DIM)]
        a = agent.select_action(state, greedy=True)
        assert isinstance(a, int)
        assert 0 <= a < N_ACTIONS


def test_rl_agent_epsilon_zero_is_deterministic(agent):
    """With epsilon=0, the same state always gives the same action."""
    state = extract_state(SAMPLE_RUBY)
    actions = {agent.select_action(state, greedy=False) for _ in range(10)}
    assert len(actions) == 1


def test_rl_agent_epsilon_one_is_random(tmp_weights):
    """With epsilon=1, actions should vary across random calls."""
    import random
    random.seed(42)
    ag = RLAgent(weights_path=tmp_weights, epsilon=1.0)
    state = extract_state(SAMPLE_RUBY)
    actions = {ag.select_action(state, greedy=False) for _ in range(50)}
    assert len(actions) > 1, "Expected at least 2 distinct actions with epsilon=1"


def test_rl_agent_q_values_keys(agent):
    q = agent.q_values(SAMPLE_RUBY)
    assert set(q.keys()) == set(ACTIONS)
    assert all(isinstance(v, float) for v in q.values())


def test_rl_agent_best_variant_returns_known_action(agent):
    variant = agent.best_variant(SAMPLE_RUBY)
    assert variant in ACTIONS


# ── ReplayBuffer ──────────────────────────────────────────────────────────────

def test_replay_buffer_push_and_len():
    buf = ReplayBuffer(capacity=10)
    for i in range(5):
        buf.push([0.0]*5, 0, 0.5, [0.0]*5, True)
    assert len(buf) == 5


def test_replay_buffer_capacity_enforced():
    buf = ReplayBuffer(capacity=3)
    for i in range(10):
        buf.push([float(i)]*5, 0, 0.5, [0.0]*5, True)
    assert len(buf) == 3


def test_replay_buffer_sample_size():
    buf = ReplayBuffer()
    for _ in range(50):
        buf.push([0.0]*5, 0, 0.5, [0.0]*5, True)
    batch = buf.sample(16)
    assert len(batch) == 16


# ── DQN training ──────────────────────────────────────────────────────────────

def _fill_buffer(agent: RLAgent, n: int = BATCH_SIZE + 5) -> None:
    """Push n synthetic experiences into the agent's buffer."""
    for i in range(n):
        state  = [float(i % 2)] * STATE_DIM
        action = i % N_ACTIONS
        reward = float(i % 2)
        agent.push_experience(state, action, reward, [0.0] * STATE_DIM, True)


def test_train_step_returns_none_when_buffer_empty(agent):
    assert agent.train_step() is None


def test_train_step_returns_loss_when_enough_data(agent):
    _fill_buffer(agent)
    loss = agent.train_step()
    assert loss is not None
    assert loss >= 0.0


def test_train_n_steps_loss_list(agent):
    _fill_buffer(agent, n=200)
    losses = agent.train_n_steps(20)
    assert len(losses) == 20
    assert all(l >= 0 for l in losses)


def test_epsilon_decays_during_training(tmp_weights):
    ag = RLAgent(weights_path=tmp_weights, epsilon=1.0)
    _fill_buffer(ag, n=200)
    ag.train_n_steps(50)
    assert ag.epsilon < 1.0


def test_stats_after_training(agent):
    _fill_buffer(agent)
    agent.train_step()
    s = agent.stats
    assert s["steps"] == 1
    assert s["buffer_size"] >= BATCH_SIZE
    assert isinstance(s["avg_loss_100"], float)


# ── Persistence ───────────────────────────────────────────────────────────────

def test_save_and_reload(tmp_weights):
    ag1 = RLAgent(weights_path=tmp_weights, epsilon=0.42)
    _fill_buffer(ag1)
    ag1.train_n_steps(5)
    ag1.save()

    ag2 = RLAgent(weights_path=tmp_weights)
    assert ag2.epsilon == pytest.approx(ag1.epsilon, abs=0.001)
    assert ag2._step == ag1._step


def test_weights_file_created_on_save(tmp_weights):
    ag = RLAgent(weights_path=tmp_weights)
    ag.save()
    assert tmp_weights.exists()


# ── Trainer ───────────────────────────────────────────────────────────────────

def test_record_to_experience_valid():
    rec = {
        "prompt_variant": "v1_minimal",
        "score": 0.85,
        "ruby_len": 400,
    }
    exp = _record_to_experience(rec)
    assert exp is not None
    state, action, reward, next_state, done = exp
    assert len(state) == STATE_DIM
    assert action == ACTIONS.index("v1_minimal")
    assert reward == pytest.approx(0.85)
    assert done is True


def test_record_to_experience_unknown_variant():
    rec = {"prompt_variant": "nonexistent", "score": 0.5, "ruby_len": 100}
    assert _record_to_experience(rec) is None


def test_train_from_memory_with_data(tmp_memory, tmp_weights):
    # Seed memory with enough records to fill the replay buffer
    for i in range(50):
        tmp_memory.add_conversion(
            filename=f"f{i}.rb",
            ruby_code="x" * 300,
            python_code="y",
            score=0.7,
            tokens=100,
            elapsed_s=1.0,
            prompt_variant=ACTIONS[i % N_ACTIONS],
        )

    ag = RLAgent(weights_path=tmp_weights)
    result = train_from_memory(tmp_memory, ag, n_steps=5, verbose=False)
    assert result["experiences_loaded"] == 50
    # We need BATCH_SIZE=32 in buffer; 50 > 32 → training should happen
    assert result["gradient_steps"] == 5
    assert result["final_loss"] is not None


def test_train_from_memory_skips_unknown_variants(tmp_memory, tmp_weights):
    tmp_memory.add_conversion(
        filename="x.rb", ruby_code="x", python_code="y",
        score=0.5, tokens=10, elapsed_s=0.1,
        prompt_variant="unknown_variant",
    )
    ag = RLAgent(weights_path=tmp_weights)
    result = train_from_memory(tmp_memory, ag, n_steps=1, verbose=False)
    assert result["experiences_loaded"] == 0
    assert result["experiences_skipped"] == 1


def test_train_from_memory_no_data(tmp_memory, tmp_weights):
    ag = RLAgent(weights_path=tmp_weights)
    result = train_from_memory(tmp_memory, ag, n_steps=10, verbose=False)
    assert result["experiences_loaded"] == 0
    assert result["gradient_steps"] == 0


# ── Improvement over synthetic training ───────────────────────────────────────

def test_q_values_change_after_training(tmp_weights):
    """Q-values for a fixed state should shift after targeted training."""
    ag = RLAgent(weights_path=tmp_weights, epsilon=0.0)
    state = [0.5, 0.1, 0.05, 0.0, 1.0]

    q_before = ag.q_values(SAMPLE_RUBY)

    # Repeatedly reward action 2 → v3_examples
    for _ in range(200):
        ag.push_experience(state, 2, 1.0, [0.0]*5, True)
        ag.push_experience(state, 0, 0.0, [0.0]*5, True)
        ag.push_experience(state, 1, 0.0, [0.0]*5, True)
    ag.train_n_steps(100)

    q_after = ag.q_values(SAMPLE_RUBY)
    # Q-values must have changed
    assert q_before != q_after
    # The rewarded action should have the highest Q-value
    best = max(q_after, key=q_after.get)
    assert best == "v3_examples"
