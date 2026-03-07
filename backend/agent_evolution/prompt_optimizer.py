"""
agent_evolution.prompt_optimizer
=================================
Adapter layer that integrates the PromptOptimizer from agent_swarm into the
agent_evolution package and wires it into the APScheduler.

The actual Thompson-Sampling and mutation logic lives in:
    agent_swarm.prompt_optimizer.PromptOptimizer

This module provides:
    - EvolutionPromptOptimizer  : thin subclass with per-run logging & stats
    - schedule_weekly()         : registers the weekly optimisation job
    - run_optimization_once()   : callable for the manual /evolution/optimize endpoint

Architecture
------------
                SwarmMemory (JSON)
                      │
        ┌─────────────▼─────────────┐
        │  EvolutionPromptOptimizer  │
        │  ┌─────────────────────┐  │
        │  │  Thompson Sampling  │  │  ◄─ select_variant()
        │  └─────────────────────┘  │
        │  ┌─────────────────────┐  │
        │  │   mutate_prompt()   │  │  ◄─ create new variants from champion
        │  └─────────────────────┘  │
        │  ┌─────────────────────┐  │
        │  │ run_optimization_   │  │  ◄─ weekly APScheduler job
        │  │      cycle()        │  │
        │  └─────────────────────┘  │
        └───────────────────────────┘
                      │
                      ▼
        GenerationAgent._variants  (injected via update_variants())
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from agent_swarm.memory import SwarmMemory
from agent_swarm.prompt_optimizer import PromptOptimizer
from agent_swarm.generation_agent import PROMPT_VARIANTS

if TYPE_CHECKING:
    from apscheduler.schedulers.background import BackgroundScheduler

log = logging.getLogger(__name__)

_DEFAULT_MEMORY = Path(__file__).parent.parent / "agent_swarm" / "memory.json"


# ── Extended optimizer with evolution-layer logging ───────────────────────────

class EvolutionPromptOptimizer(PromptOptimizer):
    """
    Subclass of PromptOptimizer that records each optimisation run
    back into SwarmMemory as a run summary.
    """

    def run_optimization_cycle(
        self, current_variants: dict[str, str]
    ) -> dict[str, str]:
        t0 = time.perf_counter()
        before = set(current_variants)

        updated = super().run_optimization_cycle(current_variants)

        after = set(updated)
        added   = sorted(after - before)
        removed = sorted(before - after)
        elapsed = round(time.perf_counter() - t0, 3)

        summary = {
            "event":    "prompt_optimization",
            "elapsed_s": elapsed,
            "variants_before": len(before),
            "variants_after":  len(after),
            "added":    added,
            "removed":  removed,
        }
        try:
            self.memory.add_run_summary(summary)
        except Exception as exc:
            log.warning("Could not save optimization summary: %s", exc)

        log.info(
            "PromptOptimizer cycle: +%d added, -%d removed, %.3f s",
            len(added), len(removed), elapsed,
        )
        return updated


# ── Public helpers ─────────────────────────────────────────────────────────────

def run_optimization_once(
    memory: SwarmMemory | None = None,
    base_variants: dict[str, str] | None = None,
) -> dict:
    """
    Run one full optimisation cycle and return a result dict.

    Used by the manual ``POST /evolution/optimize`` endpoint.
    """
    mem = memory or SwarmMemory(path=_DEFAULT_MEMORY)
    base = base_variants if base_variants is not None else dict(PROMPT_VARIANTS)
    optimizer = EvolutionPromptOptimizer(mem)
    updated = optimizer.run_optimization_cycle(base)
    added   = [vid for vid in updated if vid not in base]
    removed = [vid for vid in base if vid not in updated]
    return {
        "status":         "ok",
        "variants_total": len(updated),
        "added":          added,
        "removed":        removed,
        "variants":       list(updated.keys()),
    }


def schedule_weekly(
    scheduler: BackgroundScheduler,
    memory: SwarmMemory | None = None,
) -> None:
    """
    Register a weekly APScheduler job that runs the prompt optimisation cycle.

    Call from ``backend/app/main.py`` lifespan:

        from agent_evolution.prompt_optimizer import schedule_weekly
        schedule_weekly(_scheduler, _swarm_memory)

    The job runs every Sunday at 03:00 UTC to minimise overlap with peak traffic.
    """
    mem = memory or SwarmMemory(path=_DEFAULT_MEMORY)

    def _job() -> None:
        log.info("[PromptOptimizer] Weekly job started.")
        try:
            result = run_optimization_once(mem)
            log.info(
                "[PromptOptimizer] Done: +%d / -%d, total=%d variants",
                len(result["added"]), len(result["removed"]), result["variants_total"],
            )
        except Exception as exc:
            log.error("[PromptOptimizer] Weekly job failed: %s", exc, exc_info=True)

    scheduler.add_job(
        _job,
        trigger="cron",
        day_of_week="sun",
        hour=3,
        minute=0,
        id="weekly_prompt_optimization",
        replace_existing=True,
    )
    log.info("[PromptOptimizer] Weekly job registered (Sunday 03:00 UTC).")
