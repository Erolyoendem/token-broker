"""
RLAgent – Deep Q-Network agent for prompt-variant selection.

State space (5 continuous features, all normalised to [0, 1]):
  0  ruby_len       – source code length / 2000
  1  num_methods    – count of `def ` tokens / 20
  2  num_classes    – count of `class ` tokens / 10
  3  has_loops      – 1 if `.each` / `while` / `for ` present, else 0
  4  has_blocks     – 1 if `do |` present, else 0

Action space (3 discrete actions):
  0 → "v1_minimal"
  1 → "v2_structured"
  2 → "v3_examples"

Reward: evaluation score in [0, 1] returned by EvaluationAgent.

Architecture: Linear(5→32) → ReLU → Linear(32→16) → ReLU → Linear(16→3)

Training: Experience Replay + DQN with a target network updated every
TARGET_UPDATE_FREQ steps.  Epsilon decays from 1.0 → 0.05 over training.
"""
from __future__ import annotations

import collections
import random
import re
import time
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn
import torch.optim as optim

# ── Action space ───────────────────────────────────────────────────────────────
ACTIONS: list[str] = ["v1_minimal", "v2_structured", "v3_examples"]
N_ACTIONS = len(ACTIONS)
STATE_DIM = 5

# ── Hyperparameters ────────────────────────────────────────────────────────────
BUFFER_CAPACITY = 2_000
BATCH_SIZE      = 32
GAMMA           = 0.9          # discount (short-horizon tasks)
LR              = 1e-3
EPS_START       = 1.0
EPS_END         = 0.05
EPS_DECAY       = 0.995        # multiplied per step
TARGET_UPDATE   = 50           # sync target network every N steps

_DEFAULT_WEIGHTS = Path(__file__).parent / "rl_weights.pt"


# ── Feature extraction ─────────────────────────────────────────────────────────

def extract_state(ruby_code: str) -> list[float]:
    """Convert raw Ruby source into a normalised 5-dim state vector."""
    return [
        min(len(ruby_code) / 2000.0, 1.0),
        min(ruby_code.count("def ") / 20.0, 1.0),
        min(ruby_code.count("class ") / 10.0, 1.0),
        1.0 if re.search(r"\.each\b|while\b|for\s+\w", ruby_code) else 0.0,
        1.0 if "do |" in ruby_code else 0.0,
    ]


# ── Neural network ─────────────────────────────────────────────────────────────

class _QNetwork(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(STATE_DIM, 32),
            nn.ReLU(),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, N_ACTIONS),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


# ── Experience replay ─────────────────────────────────────────────────────────

Experience = collections.namedtuple(
    "Experience", ["state", "action", "reward", "next_state", "done"]
)


class ReplayBuffer:
    def __init__(self, capacity: int = BUFFER_CAPACITY) -> None:
        self._buf: collections.deque = collections.deque(maxlen=capacity)

    def push(self, *args: Any) -> None:
        self._buf.append(Experience(*args))

    def sample(self, n: int) -> list[Experience]:
        return random.sample(self._buf, n)

    def __len__(self) -> int:
        return len(self._buf)


# ── RLAgent ───────────────────────────────────────────────────────────────────

class RLAgent:
    """
    DQN-based agent that selects a prompt variant given task features.

    Inherits conceptually from BaseAgent but is synchronous (no async I/O)
    because all decisions are local CPU inference – no network calls.
    """

    def __init__(
        self,
        weights_path: Path = _DEFAULT_WEIGHTS,
        epsilon: float = EPS_START,
        device: str = "cpu",
    ) -> None:
        self.device = torch.device(device)
        self.epsilon = epsilon
        self.weights_path = weights_path
        self._step = 0

        self._policy_net = _QNetwork().to(self.device)
        self._target_net = _QNetwork().to(self.device)
        self._target_net.load_state_dict(self._policy_net.state_dict())
        self._target_net.eval()

        self._optimizer = optim.Adam(self._policy_net.parameters(), lr=LR)
        self._buffer = ReplayBuffer(BUFFER_CAPACITY)
        self._loss_history: list[float] = []

        if weights_path.exists():
            self.load(weights_path)

    # ── Inference ──────────────────────────────────────────────────────────────

    def select_action(self, state: list[float], greedy: bool = False) -> int:
        """
        Epsilon-greedy action selection.

        Parameters
        ----------
        state   : 5-dim feature vector from extract_state()
        greedy  : if True, always exploit (use during evaluation)

        Returns
        -------
        int  – action index (maps to ACTIONS[i])
        """
        if not greedy and random.random() < self.epsilon:
            return random.randrange(N_ACTIONS)

        with torch.no_grad():
            t = torch.tensor(state, dtype=torch.float32, device=self.device).unsqueeze(0)
            q_vals = self._policy_net(t)
            return int(q_vals.argmax(dim=1).item())

    def best_variant(self, ruby_code: str) -> str:
        """Convenience: extract state → select action → return variant name."""
        state = extract_state(ruby_code)
        action = self.select_action(state, greedy=True)
        return ACTIONS[action]

    def q_values(self, ruby_code: str) -> dict[str, float]:
        """Return Q-values for each action (useful for debugging)."""
        state = extract_state(ruby_code)
        with torch.no_grad():
            t = torch.tensor(state, dtype=torch.float32, device=self.device).unsqueeze(0)
            q = self._policy_net(t).squeeze(0).tolist()
        return {ACTIONS[i]: round(q[i], 4) for i in range(N_ACTIONS)}

    # ── Training ───────────────────────────────────────────────────────────────

    def push_experience(
        self,
        state: list[float],
        action: int,
        reward: float,
        next_state: list[float],
        done: bool = True,
    ) -> None:
        """Add one (s, a, r, s', done) tuple to the replay buffer."""
        self._buffer.push(state, action, reward, next_state, done)

    def train_step(self) -> float | None:
        """
        Sample a mini-batch from the buffer and perform one gradient step.

        Returns loss value, or None if buffer is too small.
        """
        if len(self._buffer) < BATCH_SIZE:
            return None

        batch = self._buffer.sample(BATCH_SIZE)
        states      = torch.tensor([e.state      for e in batch], dtype=torch.float32, device=self.device)
        actions     = torch.tensor([e.action     for e in batch], dtype=torch.long,    device=self.device)
        rewards     = torch.tensor([e.reward     for e in batch], dtype=torch.float32, device=self.device)
        next_states = torch.tensor([e.next_state for e in batch], dtype=torch.float32, device=self.device)
        dones       = torch.tensor([e.done       for e in batch], dtype=torch.float32, device=self.device)

        # Q(s, a) from policy net
        q_pred = self._policy_net(states).gather(1, actions.unsqueeze(1)).squeeze(1)

        # Target: r + γ·max_a Q_target(s', a)   (zero if done)
        with torch.no_grad():
            q_next = self._target_net(next_states).max(1).values
            q_target = rewards + GAMMA * q_next * (1.0 - dones)

        loss = nn.functional.smooth_l1_loss(q_pred, q_target)

        self._optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self._policy_net.parameters(), max_norm=1.0)
        self._optimizer.step()

        self._step += 1
        loss_val = float(loss.item())
        self._loss_history.append(loss_val)

        # Decay epsilon
        self.epsilon = max(EPS_END, self.epsilon * EPS_DECAY)

        # Sync target network
        if self._step % TARGET_UPDATE == 0:
            self._target_net.load_state_dict(self._policy_net.state_dict())

        return loss_val

    def train_n_steps(self, n: int) -> list[float]:
        """Run n training steps; return list of loss values."""
        losses = []
        for _ in range(n):
            loss = self.train_step()
            if loss is not None:
                losses.append(loss)
        return losses

    # ── Persistence ────────────────────────────────────────────────────────────

    def save(self, path: Path | None = None) -> None:
        p = path or self.weights_path
        torch.save({
            "policy_state": self._policy_net.state_dict(),
            "target_state": self._target_net.state_dict(),
            "epsilon":      self.epsilon,
            "step":         self._step,
        }, p)

    def load(self, path: Path) -> None:
        ckpt = torch.load(path, map_location=self.device, weights_only=True)
        self._policy_net.load_state_dict(ckpt["policy_state"])
        self._target_net.load_state_dict(ckpt["target_state"])
        self.epsilon = ckpt.get("epsilon", EPS_END)
        self._step   = ckpt.get("step", 0)

    # ── Stats ──────────────────────────────────────────────────────────────────

    @property
    def stats(self) -> dict[str, Any]:
        recent = self._loss_history[-100:]
        return {
            "steps":        self._step,
            "epsilon":      round(self.epsilon, 4),
            "buffer_size":  len(self._buffer),
            "avg_loss_100": round(sum(recent) / len(recent), 6) if recent else None,
        }
