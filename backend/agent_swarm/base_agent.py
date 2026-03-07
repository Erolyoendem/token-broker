"""
BaseAgent – Abstract lifecycle class for all swarm agents.

Every agent has:
  setup()    – called once before the first task (acquire resources)
  run(task)  – process a single task dict, return result dict
  teardown() – called after last task (release resources)

Stats are accumulated per-instance and can be merged by the Orchestrator.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any


class AgentError(Exception):
    """Raised when an agent cannot process a task."""


class BaseAgent(ABC):
    """Abstract base for Generation and Evaluation agents."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self._calls = 0
        self._successes = 0
        self._failures = 0
        self._total_tokens = 0
        self._total_elapsed = 0.0

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def setup(self) -> None:
        """Acquire any resources (HTTP sessions, DB handles, etc.)."""

    @abstractmethod
    async def run(self, task: dict[str, Any]) -> dict[str, Any]:
        """
        Process one task.

        Parameters
        ----------
        task : dict with at least {"filename": str, "ruby_code": str}

        Returns
        -------
        dict with at least {"ok": bool, "error": str}
        """

    async def teardown(self) -> None:
        """Release resources."""

    # ── Stats helpers ──────────────────────────────────────────────────────────

    def _record(self, success: bool, tokens: int, elapsed: float) -> None:
        self._calls += 1
        self._total_tokens += tokens
        self._total_elapsed += elapsed
        if success:
            self._successes += 1
        else:
            self._failures += 1

    @property
    def stats(self) -> dict[str, Any]:
        calls = self._calls
        return {
            "agent_id": self.agent_id,
            "calls": calls,
            "successes": self._successes,
            "failures": self._failures,
            "success_rate": round(self._successes / calls, 3) if calls else 0.0,
            "total_tokens": self._total_tokens,
            "avg_tokens": round(self._total_tokens / calls, 1) if calls else 0.0,
            "avg_elapsed_s": round(self._total_elapsed / calls, 3) if calls else 0.0,
        }

    # ── Context manager support ────────────────────────────────────────────────

    async def __aenter__(self) -> "BaseAgent":
        await self.setup()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.teardown()

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.agent_id} calls={self._calls}>"
