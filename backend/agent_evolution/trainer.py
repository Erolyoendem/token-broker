"""
Trainer – Offline RL training from SwarmMemory experiences.

Workflow
--------
1. Load conversion records from SwarmMemory.
2. Convert each record to an (s, a, r, s') experience tuple:
     s  = extract_state(ruby_code)     ← not stored directly; approximated
     a  = ACTIONS.index(prompt_variant)
     r  = score (0–1)
     s' = terminal (zeros, done=True)  ← episode-level tasks
3. Push all experiences into the RLAgent's replay buffer.
4. Run N gradient steps.
5. Save updated weights.

Can be run as a one-shot CLI or scheduled via APScheduler.

Usage
-----
    python -m agent_evolution.trainer [--steps 500] [--dry-run]

Scheduled (APScheduler, daily):
    from agent_evolution.trainer import schedule_daily
    schedule_daily(scheduler)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# Allow running as `python -m agent_evolution.trainer` from backend/
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_evolution.rl_agent import RLAgent, ACTIONS, extract_state, _DEFAULT_WEIGHTS
from agent_swarm.memory import SwarmMemory

_DEFAULT_MEMORY = Path(__file__).parent.parent / "agent_swarm" / "memory.json"
_TERMINAL_STATE = [0.0] * 5   # absorbing state after episode ends


def _record_to_experience(record: dict) -> tuple | None:
    """
    Convert one SwarmMemory conversion record to an RL experience.

    The ruby_code is not stored in memory.json (only its length is), so
    we approximate the state from the stored metrics:
      ruby_len ≈ ruby_len / 2000
      num_methods ≈ 0 (not stored)
      num_classes ≈ 0 (not stored)
      has_loops   ≈ 0
      has_blocks  ≈ 0

    For richer state reconstruction, store ruby_code in future runs.
    """
    variant = record.get("prompt_variant", "")
    if variant not in ACTIONS:
        return None

    action = ACTIONS.index(variant)
    reward = float(record.get("score", 0.0))

    # Approximate state from stored metrics
    state = [
        min(record.get("ruby_len", 0) / 2000.0, 1.0),
        0.0,   # num_methods: not stored
        0.0,   # num_classes: not stored
        0.0,   # has_loops:   not stored
        0.0,   # has_blocks:  not stored
    ]

    return state, action, reward, _TERMINAL_STATE, True   # done=True (terminal)


def train_from_memory(
    memory: SwarmMemory,
    rl_agent: RLAgent,
    n_steps: int = 500,
    verbose: bool = True,
) -> dict:
    """
    Load experiences from memory and run n_steps of DQN training.

    Returns a dict with training statistics.
    """
    records = memory.recent_conversions(n=1000)
    pushed = 0
    skipped = 0

    for rec in records:
        exp = _record_to_experience(rec)
        if exp is None:
            skipped += 1
            continue
        rl_agent.push_experience(*exp)
        pushed += 1

    if verbose:
        print(f"[Trainer] Loaded {pushed} experiences ({skipped} skipped).")
        print(f"[Trainer] Buffer size: {len(rl_agent._buffer)} / {n_steps} steps requested.")

    losses = rl_agent.train_n_steps(n_steps)

    if verbose:
        if losses:
            print(f"[Trainer] {len(losses)} gradient steps. "
                  f"Final loss: {losses[-1]:.6f}  ε={rl_agent.epsilon:.4f}")
        else:
            print(f"[Trainer] Not enough data for training "
                  f"(need {32} experiences, have {len(rl_agent._buffer)}).")

    rl_agent.save()
    if verbose:
        print(f"[Trainer] Weights saved → {rl_agent.weights_path}")

    return {
        "experiences_loaded": pushed,
        "experiences_skipped": skipped,
        "gradient_steps": len(losses),
        "final_loss": losses[-1] if losses else None,
        "epsilon": rl_agent.epsilon,
        "buffer_size": len(rl_agent._buffer),
    }


# ── Combined online + offline training ───────────────────────────────────────

def train_combined(
    memory: SwarmMemory,
    rl_agent: RLAgent,
    dataset_manager=None,
    pair_id: str = "ruby->python",
    min_quality: float = 3.0,
    n_steps_online: int = 300,
    n_steps_offline: int = 300,
    verbose: bool = True,
) -> dict:
    """
    Run both online (SwarmMemory) and offline (DB training_pairs) training
    in a single pass, then save weights once.

    The replay buffer is shared, so both data sources contribute to every
    mini-batch, blending live experience with curated offline data.
    """
    from agent_evolution.train_from_data import train_from_db

    if verbose:
        print("[CombinedTrainer] === Phase 1: Online (SwarmMemory) ===")
    online_result = train_from_memory(memory, rl_agent, n_steps=n_steps_online, verbose=verbose)

    if verbose:
        print("[CombinedTrainer] === Phase 2: Offline (DB training_pairs) ===")
    offline_result = train_from_db(
        rl_agent,
        dataset_manager=dataset_manager,
        pair_id=pair_id,
        min_quality=min_quality,
        n_steps=n_steps_offline,
        verbose=verbose,
    )

    return {
        "online": online_result,
        "offline": offline_result,
        "total_gradient_steps": (
            online_result.get("gradient_steps", 0)
            + offline_result.get("gradient_steps", 0)
        ),
        "buffer_size": len(rl_agent._buffer),
        "epsilon": rl_agent.epsilon,
    }


# ── CLI entry point ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Train RLAgent from SwarmMemory")
    parser.add_argument("--steps",    type=int,  default=500, help="Gradient steps")
    parser.add_argument("--dry-run",  action="store_true",    help="Skip saving weights")
    parser.add_argument("--memory",   type=Path, default=_DEFAULT_MEMORY)
    parser.add_argument("--weights",  type=Path, default=_DEFAULT_WEIGHTS)
    args = parser.parse_args()

    memory   = SwarmMemory(path=args.memory)
    rl_agent = RLAgent(weights_path=args.weights)
    result   = train_from_memory(memory, rl_agent, n_steps=args.steps)

    if args.dry_run and args.weights.exists():
        args.weights.unlink()

    print("\nTraining complete:")
    for k, v in result.items():
        print(f"  {k}: {v}")


# ── APScheduler integration ────────────────────────────────────────────────────

def schedule_daily(scheduler, memory: SwarmMemory | None = None) -> None:
    """
    Register a daily training job with an existing APScheduler instance.

    Call this from backend/app/main.py lifespan:
        from agent_evolution.trainer import schedule_daily
        schedule_daily(_scheduler, _swarm_memory)
    """
    _mem = memory or SwarmMemory(path=_DEFAULT_MEMORY)
    _rl  = RLAgent()

    def _job() -> None:
        train_from_memory(_mem, _rl, n_steps=500)

    scheduler.add_job(_job, "interval", hours=24, id="rl_training_job",
                      replace_existing=True)


if __name__ == "__main__":
    main()
