"""
Multi-agent quality filter.

Three independent LLM "agents" each evaluate a code pair on a 1-5 scale.
A pair is accepted only when ≥ 2 agents agree (majority consensus).
Disagreements are escalated to Discord for human review.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from enum import IntEnum

import httpx

log = logging.getLogger(__name__)

DISCORD_WEBHOOK = ""   # injected at runtime by pipeline.py


class Rating(IntEnum):
    REJECT = 1
    POOR   = 2
    OK     = 3
    GOOD   = 4
    GREAT  = 5

    @classmethod
    def from_text(cls, text: str) -> "Rating":
        """Parse a 1-5 rating from free-form LLM text."""
        m = re.search(r"\b([1-5])\b", text)
        if m:
            return cls(int(m.group(1)))
        # Keyword fallback
        text_lower = text.lower()
        if any(w in text_lower for w in ("great", "excellent", "perfect")):
            return cls.GREAT
        if any(w in text_lower for w in ("good", "correct", "accurate")):
            return cls.GOOD
        if any(w in text_lower for w in ("ok", "acceptable", "minor")):
            return cls.OK
        if any(w in text_lower for w in ("poor", "incorrect", "broken")):
            return cls.POOR
        return cls.OK  # neutral default


@dataclass
class AgentEvaluation:
    agent_id: int
    rating: Rating
    rationale: str


@dataclass
class ConsensusResult:
    accepted: bool
    ratings: list[int]
    majority_rating: Rating
    requires_human: bool
    evaluations: list[AgentEvaluation] = field(default_factory=list)


# Agent system prompts – each emphasises a different quality dimension
_AGENT_PROMPTS = [
    (
        "You are a strict code correctness reviewer. "
        "Focus on whether the converted code is syntactically and semantically correct. "
        "Rate the pair 1 (broken) to 5 (perfect). "
        "Respond with only: RATING: <number>\\nRATIONALE: <one sentence>"
    ),
    (
        "You are an idiomatic code style reviewer. "
        "Focus on whether the converted code uses the target language's idioms and best practices. "
        "Rate the pair 1 (very un-idiomatic) to 5 (perfectly idiomatic). "
        "Respond with only: RATING: <number>\\nRATIONALE: <one sentence>"
    ),
    (
        "You are a code equivalence reviewer. "
        "Focus on whether the converted code preserves the same logic and behavior as the original. "
        "Rate the pair 1 (wrong behavior) to 5 (equivalent behavior). "
        "Respond with only: RATING: <number>\\nRATIONALE: <one sentence>"
    ),
]


class MultiAgentFilter:
    ACCEPT_RATING = Rating.OK  # minimum majority rating to auto-accept

    def __init__(
        self,
        proxy_url: str = "http://localhost:8000",
        api_key: str = "",
        discord_webhook: str = "",
    ):
        self._url = proxy_url.rstrip("/")
        self._key = api_key
        self._discord = discord_webhook

    # ── Public ────────────────────────────────────────────────────────────────

    async def evaluate(
        self,
        source_code: str,
        target_code: str,
        pair_id: str,
    ) -> ConsensusResult:
        """Run all three agents concurrently, then compute consensus."""
        tasks = [
            self._evaluate_agent(i, source_code, target_code, pair_id)
            for i in range(3)
        ]
        evaluations: list[AgentEvaluation] = await asyncio.gather(*tasks)
        return self._compute_consensus(evaluations, pair_id)

    def evaluate_sync(
        self,
        source_code: str,
        target_code: str,
        pair_id: str,
    ) -> ConsensusResult:
        """Synchronous wrapper for non-async contexts."""
        return asyncio.run(self.evaluate(source_code, target_code, pair_id))

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _evaluate_agent(
        self,
        agent_id: int,
        source_code: str,
        target_code: str,
        pair_id: str,
    ) -> AgentEvaluation:
        system_prompt = _AGENT_PROMPTS[agent_id]
        user_content = (
            f"Language pair: {pair_id}\n\n"
            f"SOURCE CODE:\n```\n{source_code[:1500]}\n```\n\n"
            f"CONVERTED CODE:\n```\n{target_code[:1500]}\n```"
        )
        try:
            content = await self._llm_call(system_prompt, user_content)
            rating = Rating.from_text(content)
            rationale = self._extract_rationale(content)
        except Exception as e:
            log.warning("Agent %d failed: %s", agent_id, e)
            rating = Rating.OK
            rationale = f"evaluation failed: {e}"

        return AgentEvaluation(agent_id=agent_id, rating=rating, rationale=rationale)

    def _compute_consensus(
        self,
        evaluations: list[AgentEvaluation],
        pair_id: str,
    ) -> ConsensusResult:
        ratings = [e.rating for e in evaluations]
        counts: dict[Rating, int] = {}
        for r in ratings:
            counts[r] = counts.get(r, 0) + 1

        majority_rating, majority_count = max(counts.items(), key=lambda kv: kv[1])
        has_consensus = majority_count >= 2
        accepted = has_consensus and majority_rating >= self.ACCEPT_RATING
        requires_human = not has_consensus

        if requires_human and self._discord:
            asyncio.create_task(
                self._notify_discord(evaluations, pair_id, ratings)
            )

        return ConsensusResult(
            accepted=accepted,
            ratings=[r.value for r in ratings],
            majority_rating=majority_rating,
            requires_human=requires_human,
            evaluations=evaluations,
        )

    async def _llm_call(self, system: str, user: str) -> str:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                f"{self._url}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                },
                json={
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ]
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def _notify_discord(
        self,
        evaluations: list[AgentEvaluation],
        pair_id: str,
        ratings: list[Rating],
    ) -> None:
        if not self._discord:
            return
        lines = [
            f"**TokenBroker | Human Review Requested**",
            f"Pair: `{pair_id}` | Ratings: {[r.value for r in ratings]}",
        ]
        for e in evaluations:
            lines.append(f"Agent {e.agent_id}: {e.rating.name} – {e.rationale}")
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(self._discord, json={"content": "\n".join(lines)})
        except Exception as exc:
            log.warning("Discord notify failed: %s", exc)

    @staticmethod
    def _extract_rationale(text: str) -> str:
        m = re.search(r"RATIONALE:\s*(.+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else text[:100]
