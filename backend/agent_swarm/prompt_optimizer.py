"""
PromptOptimizer – Thompson-Sampling-basierte automatische Prompt-Optimierung.

Liest Erfolgsstatistiken aus SwarmMemory, wählt via Thompson Sampling die
beste Variante, mutiert Prompts durch vordefinierte Transformationen und
ersetzt wöchentlich die schlechtesten Varianten.
"""
from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Optional

from .memory import SwarmMemory

log = logging.getLogger(__name__)

# ── Mutationsregeln ────────────────────────────────────────────────────────────
# Jede Mutation ist ein (old, new)-Paar. Die erste passende Ersetzung wird
# angewendet; greift keine, wird ein Zusatz ans Ende gehängt.

MUTATIONS: list[tuple[str, str]] = [
    ("Output only", "Return only"),
    ("output only", "return only"),
    ("expert software engineer", "senior software engineer"),
    ("idiomatic Python 3", "clean, idiomatic Python 3"),
    ("No explanation", "No prose, no explanation"),
    ("no markdown fences", "no code fences, no markdown"),
    ("Convert the given Ruby code", "Translate the provided Ruby code"),
    ("strictly", "exactly"),
    ("sensible", "appropriate"),
    ("runnable Python code", "executable Python 3 code"),
]

EXPLORATION_SUFFIX = "\nBe concise. Output only the converted Python code."


def _thompson_sample(calls: int, successes: int) -> float:
    """Draw one sample from Beta(successes+1, failures+1)."""
    failures = calls - successes
    return random.betavariate(successes + 1, failures + 1)


class PromptOptimizer:
    """
    Manages prompt variant evolution using Thompson Sampling.

    Attributes:
        memory: Shared SwarmMemory instance.
        max_variants: Maximum total variants (base + mutants) to keep alive.
        worst_cutoff: Bottom fraction of variants eligible for replacement.
    """

    def __init__(
        self,
        memory: SwarmMemory,
        max_variants: int = 8,
        worst_cutoff: float = 0.25,
    ) -> None:
        self.memory = memory
        self.max_variants = max_variants
        self.worst_cutoff = worst_cutoff

    # ── Public API ─────────────────────────────────────────────────────────────

    def select_variant(self, available: list[str]) -> str:
        """
        Thompson Sampling: draw Beta(α, β) for each variant and return argmax.
        Variants never seen get priority (infinite uncertainty → explore first).
        """
        stats = self.memory.prompt_stats()
        best_variant = available[0]
        best_sample = -1.0

        for vid in available:
            if vid not in stats or stats[vid]["calls"] == 0:
                # Unseen → return immediately (explore unknown)
                return vid
            s = stats[vid]
            sample = _thompson_sample(s["calls"], s["successes"])
            if sample > best_sample:
                best_sample = sample
                best_variant = vid

        return best_variant

    def mutate_prompt(self, variant_id: str, base_text: str) -> tuple[str, str]:
        """
        Apply one mutation from MUTATIONS to base_text.
        Returns (new_variant_id, mutated_text).
        The new ID is derived from the source variant + a short hash.
        """
        mutated = base_text
        applied = False

        # Try mutations in shuffled order for diversity
        mutations = MUTATIONS[:]
        random.shuffle(mutations)
        for old, new in mutations:
            if old in mutated:
                mutated = mutated.replace(old, new, 1)
                applied = True
                break

        if not applied:
            mutated = mutated + EXPLORATION_SUFFIX

        suffix = hex(abs(hash(mutated)))[-4:]
        new_id = f"{variant_id}_mut_{suffix}"
        return new_id, mutated

    def run_optimization_cycle(
        self, current_variants: dict[str, str]
    ) -> dict[str, str]:
        """
        Weekly cycle:
        1. Score all variants via Thompson Sampling.
        2. Identify worst performers (bottom worst_cutoff fraction).
        3. Mutate the best variant to create replacements.
        4. Return updated variant dict.
        """
        if not current_variants:
            return current_variants

        stats = self.memory.prompt_stats()
        scored: list[tuple[float, str]] = []

        for vid in current_variants:
            if vid in stats and stats[vid]["calls"] > 0:
                s = stats[vid]
                score = _thompson_sample(s["calls"], s["successes"])
            else:
                score = 0.5  # neutral prior for unseen
            scored.append((score, vid))

        scored.sort(reverse=True)  # best first

        n_replace = max(1, int(len(scored) * self.worst_cutoff))
        worst_ids = [vid for _, vid in scored[-n_replace:]]
        best_id = scored[0][1]
        best_text = current_variants[best_id]

        updated = dict(current_variants)
        for wid in worst_ids:
            if wid == best_id:
                continue  # never replace the champion
            new_id, new_text = self.mutate_prompt(best_id, best_text)
            del updated[wid]
            updated[new_id] = new_text
            log.info("Replaced variant %s with mutation %s", wid, new_id)

        # Trim to max_variants if needed
        while len(updated) > self.max_variants:
            # Remove oldest mutant (last in dict after Python 3.7+)
            drop_id = list(updated.keys())[-1]
            if drop_id != best_id:
                del updated[drop_id]
                log.info("Trimmed variant %s (max_variants=%d)", drop_id, self.max_variants)
            else:
                break

        return updated
