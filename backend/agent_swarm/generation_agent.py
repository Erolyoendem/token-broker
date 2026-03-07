"""
GenerationAgent – Converts Ruby code to Python via the TokenBroker proxy.

Uses epsilon-greedy prompt-variant selection: the variant with the highest
historical success rate is preferred, but 10% of the time a random variant
is tried (exploration). After each call, the result is recorded back in
SwarmMemory so the system learns over runs.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any

import aiohttp
from dotenv import load_dotenv

from .base_agent import BaseAgent, AgentError
from .memory import SwarmMemory

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


def _strip_fences(text: str) -> str:
    text = re.sub(r"^```[a-z]*\n?", "", text.strip())
    return text.rstrip("`").strip()


class GenerationAgent(BaseAgent):
    """Calls the LLM proxy to generate Python from Ruby code."""

    def __init__(self, agent_id: str, memory: SwarmMemory, epsilon: float = 0.1) -> None:
        super().__init__(agent_id)
        self.memory = memory
        self.epsilon = epsilon
        self._session: aiohttp.ClientSession | None = None

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
        variant_id = self.memory.best_prompt_variant(VARIANT_IDS, self.epsilon)
        system_prompt = PROMPT_VARIANTS[variant_id]

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
