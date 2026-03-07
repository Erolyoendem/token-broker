"""
ExperimentManager – lightweight A/B testing for agent configurations.

An *experiment* is identified by a name and has two or more *variants*.
Each variant is a dict of configuration overrides (e.g. different prompts or
models).  Tasks are assigned to variants uniformly at random.

Experiment state is persisted in a JSON file so it survives restarts.

Usage
-----
    em = ExperimentManager()

    em.create("prompt_v2_test", variants=[
        {"name": "control",   "system_prompt": "You are a helpful assistant."},
        {"name": "treatment", "system_prompt": "You are an expert Python engineer."},
    ])

    variant = em.assign("prompt_v2_test")   # -> {"name": "treatment", ...}

    em.record_outcome("prompt_v2_test", variant["name"], success=True, score=0.9)

    summary = em.summary("prompt_v2_test")  # stats per variant + winner
"""
from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path
from typing import Any

DEFAULT_STATE = Path(__file__).parent / "experiments.json"


class ExperimentManager:
    def __init__(self, state_path: Path | str = DEFAULT_STATE) -> None:
        self._path = Path(state_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._state: dict[str, Any] = self._load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._state, indent=2))

    # ── Experiment lifecycle ───────────────────────────────────────────────────

    def create(
        self,
        name: str,
        variants: list[dict[str, Any]],
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a new experiment.  Raises if name exists unless overwrite=True."""
        if name in self._state and not overwrite:
            raise ValueError(f"Experiment '{name}' already exists.")
        if len(variants) < 2:
            raise ValueError("Need at least 2 variants for an A/B test.")
        for v in variants:
            if "name" not in v:
                raise ValueError("Each variant must have a 'name' key.")

        self._state[name] = {
            "created_at": time.time(),
            "status": "running",
            "variants": variants,
            "outcomes": {v["name"]: {"success": 0, "failure": 0, "scores": []} for v in variants},
        }
        self._save()

    def stop(self, name: str) -> None:
        """Mark experiment as stopped (no more assignments)."""
        self._require(name)
        self._state[name]["status"] = "stopped"
        self._state[name]["stopped_at"] = time.time()
        self._save()

    def freeze(self, name: str, winner: str) -> None:
        """Freeze an experiment – record the winning variant."""
        self._require(name)
        variants = {v["name"] for v in self._state[name]["variants"]}
        if winner not in variants:
            raise ValueError(f"Unknown variant '{winner}'.")
        self._state[name]["status"] = "frozen"
        self._state[name]["winner"] = winner
        self._save()

    # ── Assignment & outcome ───────────────────────────────────────────────────

    def assign(self, name: str) -> dict[str, Any]:
        """Return a random variant config for an active experiment."""
        self._require(name)
        exp = self._state[name]
        if exp["status"] != "running":
            raise RuntimeError(f"Experiment '{name}' is not running (status={exp['status']}).")
        return random.choice(exp["variants"])

    def record_outcome(
        self,
        name: str,
        variant_name: str,
        *,
        success: bool,
        score: float = 0.0,
    ) -> None:
        self._require(name)
        outcomes = self._state[name]["outcomes"]
        if variant_name not in outcomes:
            raise ValueError(f"Unknown variant '{variant_name}' in experiment '{name}'.")
        key = "success" if success else "failure"
        outcomes[variant_name][key] += 1
        outcomes[variant_name]["scores"].append(round(score, 4))
        self._save()

    # ── Analysis ───────────────────────────────────────────────────────────────

    def summary(self, name: str) -> dict[str, Any]:
        """Return per-variant stats and a suggested winner."""
        self._require(name)
        exp = self._state[name]
        variant_stats = []
        for variant_name, data in exp["outcomes"].items():
            total = data["success"] + data["failure"]
            scores = data["scores"]
            variant_stats.append({
                "name": variant_name,
                "calls": total,
                "successes": data["success"],
                "success_rate": round(data["success"] / total, 3) if total else 0.0,
                "avg_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
            })

        # Suggest winner by success_rate; fall back to avg_score on tie
        sorted_variants = sorted(
            variant_stats,
            key=lambda v: (v["success_rate"], v["avg_score"]),
            reverse=True,
        )
        suggested_winner = sorted_variants[0]["name"] if sorted_variants else None

        return {
            "name": name,
            "status": exp["status"],
            "variants": variant_stats,
            "suggested_winner": suggested_winner,
            "winner": exp.get("winner"),
        }

    def list_experiments(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "status": data["status"],
                "variant_count": len(data["variants"]),
                "created_at": data["created_at"],
            }
            for name, data in self._state.items()
        ]

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _require(self, name: str) -> None:
        if name not in self._state:
            raise KeyError(f"Experiment '{name}' not found.")

    def reset(self) -> None:
        """Clear all experiments – for tests."""
        self._state = {}
        if self._path.exists():
            self._path.unlink()
