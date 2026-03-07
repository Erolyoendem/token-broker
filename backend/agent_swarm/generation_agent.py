"""
GenerationAgent – Converts Ruby code to Python via the TokenBroker proxy.

Selection strategy (layered):
  1. With probability NOVEL_EPSILON (5 %): pick a variant that has never been
     tried – forces exploration of optimizer-generated mutations.
  2. Otherwise: Thompson Sampling via PromptOptimizer (draws from Beta
     posterior per variant, returns argmax).
  3. Fallback: epsilon-greedy on SwarmMemory (legacy, epsilon=10 %).

After each call the result is recorded back in SwarmMemory so all selection
methods learn from the same signal.
"""
from __future__ import annotations

import os
import random
import re
import time
from typing import Any

import aiohttp
from dotenv import load_dotenv

from .base_agent import BaseAgent, AgentError
from .memory import SwarmMemory
from .prompt_optimizer import PromptOptimizer

load_dotenv()

PROXY_URL = os.getenv(
    "TOKENBROKER_PROXY_URL",
    "https://yondem-production.up.railway.app/v1/chat/completions",
)
API_KEY = os.getenv("TOKENBROKER_KEY", "tkb_test_123")

# ── Prompt variants ────────────────────────────────────────────────────────────
# Each variant is a different system prompt. The swarm learns which produces
# the highest-scoring (evaluatable) Python output.

PROMPT_VARIANTS: dict[str, str] = {
    "v1_minimal": (
        "You are a Ruby-to-Python code converter. "
        "Output only valid Python code. No explanation, no markdown fences."
    ),
    "v2_structured": (
        "You are an expert software engineer specialising in Ruby-to-Python migration. "
        "Convert the given Ruby code to idiomatic Python 3. "
        "Rules: output ONLY runnable Python code, no comments, no markdown fences. "
        "Preserve all logic, class structure, and method names where possible."
    ),
    "v3_examples": (
        "Convert Ruby to Python. Follow these rules strictly:\n"
        "1. Output only Python code – no explanation, no ```fences```.\n"
        "2. Replace Ruby idioms with Pythonic equivalents "
        "(e.g. attr_accessor → @property or plain attributes, "
        "puts → print, symbols → strings).\n"
        "3. Keep class and method names identical where sensible.\n"
        "4. The output must be syntactically valid Python 3."
    ),
}

VARIANT_IDS = list(PROMPT_VARIANTS.keys())

# Probability of forcing an unexplored (mutant) variant
NOVEL_EPSILON: float = 0.05


def _strip_fences(text: str) -> str:
    text = re.sub(r"^```[a-z]*\n?", "", text.strip())
    return text.rstrip("`").strip()


class GenerationAgent(BaseAgent):
    """Calls the LLM proxy to generate Python from Ruby code."""

    def __init__(self, agent_id: str, memory: SwarmMemory, epsilon: float = 0.1) -> None:
        super().__init__(agent_id)
        self.memory = memory
        self.epsilon = epsilon
        self.optimizer = PromptOptimizer(memory)
        # Live variant pool: base variants + optimizer mutations
        self._variants: dict[str, str] = dict(PROMPT_VARIANTS)
        self._session: aiohttp.ClientSession | None = None

    def _select_variant(self) -> str:
        """
        Three-tier selection:
        1. NOVEL_EPSILON chance → pick any unseen variant (exploration).
        2. Thompson Sampling across full _variants pool.
        3. If pool somehow empty, fall back to epsilon-greedy on base variants.
        """
        all_ids = list(self._variants.keys())
        stats = self.memory.prompt_stats()
        unseen = [vid for vid in all_ids if vid not in stats or stats[vid]["calls"] == 0]

        # Tier 1: force novel exploration
        if unseen and random.random() < NOVEL_EPSILON:
            return random.choice(unseen)

        # Tier 2: Thompson Sampling
        return self.optimizer.select_variant(all_ids)

    def update_variants(self, new_variants: dict[str, str]) -> None:
        """Called by the weekly scheduler to inject optimizer mutations."""
        self._variants = new_variants

    async def setup(self) -> None:
        connector = aiohttp.TCPConnector(limit=5)
        self._session = aiohttp.ClientSession(connector=connector)

    async def teardown(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def run(self, task: dict[str, Any]) -> dict[str, Any]:
        """
        task: {"filename": str, "ruby_code": str}
        returns: {"ok": bool, "python_code": str, "tokens": int,
                  "elapsed_s": float, "prompt_variant": str, "error": str}
        """
        if not self._session:
            raise AgentError(f"{self.agent_id}: setup() was not called")

        ruby_code = task["ruby_code"]
        # Honour explicit RL override from Orchestrator; otherwise use layered selection
        rl_override = task.get("_rl_variant") or getattr(self, "_rl_variant_override", None)
        if rl_override and rl_override in self._variants:
            variant_id = rl_override
        else:
            variant_id = self._select_variant()
        system_prompt = self._variants[variant_id]

        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Convert to Python:\n\n{ruby_code}"},
            ]
        }
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        }

        t0 = time.perf_counter()
        try:
            async with self._session.post(
                PROXY_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=90),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

            content = data["choices"][0]["message"]["content"]
            python_code = _strip_fences(content)
            tokens = data.get("usage", {}).get("total_tokens", 0)
            elapsed = round(time.perf_counter() - t0, 3)

            self._record(success=True, tokens=tokens, elapsed=elapsed)
            self.memory.record_prompt_result(variant_id, success=True, tokens=tokens)

            return {
                "ok": True,
                "python_code": python_code,
                "tokens": tokens,
                "elapsed_s": elapsed,
                "prompt_variant": variant_id,
                "error": "",
            }

        except Exception as exc:
            elapsed = round(time.perf_counter() - t0, 3)
            self._record(success=False, tokens=0, elapsed=elapsed)
            self.memory.record_prompt_result(variant_id, success=False, tokens=0)
            return {
                "ok": False,
                "python_code": "",
                "tokens": 0,
                "elapsed_s": elapsed,
                "prompt_variant": variant_id,
                "error": str(exc),
            }
