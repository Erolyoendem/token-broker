"""
SwarmMemory – Persistent storage for the agent swarm.

Stores:
  - conversion records (ruby → python pairs with quality scores)
  - prompt variant stats (calls, successes → success rate)
  - run-level summaries (for meta-cognition)

Backed by a local JSON file. In production this would be Supabase
table `agent_prompts` + `training_pairs`, but the interface is identical.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path(__file__).parent / "memory.json"

_INITIAL_STATE: dict[str, Any] = {
    "conversions": [],          # list[ConversionRecord]
    "prompt_variants": {},      # variant_id → {calls, successes, total_tokens}
    "run_summaries": [],        # list[RunSummary]
    "meta": {
        "total_conversions": 0,
        "total_tokens": 0,
        "created_at": "",
        "last_updated": "",
    },
}


class SwarmMemory:
    """Thread-safe (via in-process lock) persistent swarm memory."""

    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        self.path = path
        self._state: dict[str, Any] = self._load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, KeyError):
                pass
        state = json.loads(json.dumps(_INITIAL_STATE))  # deep copy
        state["meta"]["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return state

    def save(self) -> None:
        self._state["meta"]["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.path.write_text(
            json.dumps(self._state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Conversion records ─────────────────────────────────────────────────────

    def add_conversion(
        self,
        *,
        filename: str,
        ruby_code: str,
        python_code: str,
        score: float,
        tokens: int,
        elapsed_s: float,
        prompt_variant: str,
        error: str = "",
    ) -> None:
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "filename": filename,
            "ruby_len": len(ruby_code),
            "python_len": len(python_code),
            "score": round(score, 3),
            "tokens": tokens,
            "elapsed_s": round(elapsed_s, 3),
            "prompt_variant": prompt_variant,
            "error": error,
        }
        self._state["conversions"].append(record)
        self._state["meta"]["total_conversions"] += 1
        self._state["meta"]["total_tokens"] += tokens
        self.save()

    def recent_conversions(self, n: int = 50) -> list[dict]:
        return self._state["conversions"][-n:]

    # ── Prompt variant tracking (epsilon-greedy RL) ────────────────────────────

    def record_prompt_result(
        self, variant_id: str, success: bool, tokens: int
    ) -> None:
        variants = self._state["prompt_variants"]
        if variant_id not in variants:
            variants[variant_id] = {"calls": 0, "successes": 0, "total_tokens": 0}
        v = variants[variant_id]
        v["calls"] += 1
        v["total_tokens"] += tokens
        if success:
            v["successes"] += 1
        self.save()

    def best_prompt_variant(self, available: list[str], epsilon: float = 0.1) -> str:
        """Epsilon-greedy selection: exploit best or explore randomly."""
        import random

        variants = self._state["prompt_variants"]
        # Explore: with probability epsilon pick a random variant
        if random.random() < epsilon:
            return random.choice(available)

        # Exploit: pick the variant with the highest success rate (min 1 call)
        best, best_rate = available[0], -1.0
        for vid in available:
            stats = variants.get(vid, {"calls": 0, "successes": 0})
            if stats["calls"] == 0:
                return vid  # always try unseen variants first
            rate = stats["successes"] / stats["calls"]
            if rate > best_rate:
                best, best_rate = vid, rate
        return best

    def prompt_stats(self) -> dict[str, dict]:
        out = {}
        for vid, v in self._state["prompt_variants"].items():
            calls = v["calls"]
            out[vid] = {
                "calls": calls,
                "successes": v["successes"],
                "success_rate": round(v["successes"] / calls, 3) if calls else 0.0,
                "avg_tokens": round(v["total_tokens"] / calls, 1) if calls else 0.0,
            }
        return out

    # ── Run summaries ──────────────────────────────────────────────────────────

    def add_run_summary(self, summary: dict) -> None:
        summary["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._state["run_summaries"].append(summary)
        self.save()

    def run_summaries(self) -> list[dict]:
        return self._state["run_summaries"]

    # ── Aggregate stats ────────────────────────────────────────────────────────

    def aggregate_stats(self) -> dict:
        convs = self._state["conversions"]
        if not convs:
            return {
                "total_conversions": 0,
                "success_rate": 0.0,
                "avg_score": 0.0,
                "avg_tokens": 0.0,
                "avg_elapsed_s": 0.0,
                "prompt_stats": {},
                "runs": len(self._state["run_summaries"]),
            }
        successful = [c for c in convs if c["score"] >= 0.5]
        return {
            "total_conversions": len(convs),
            "success_rate": round(len(successful) / len(convs), 3),
            "avg_score": round(sum(c["score"] for c in convs) / len(convs), 3),
            "avg_tokens": round(sum(c["tokens"] for c in convs) / len(convs), 1),
            "avg_elapsed_s": round(
                sum(c["elapsed_s"] for c in convs) / len(convs), 3
            ),
            "prompt_stats": self.prompt_stats(),
            "runs": len(self._state["run_summaries"]),
        }
