"""
Offline trainer – Behavior Cloning from `training_pairs` DB table.

Pipeline
--------
1. Fetch accepted training pairs from Supabase (quality_score ≥ min_quality,
   status = 'accepted', 3-agent consensus).
2. For each pair:
     state  = extract_state(source_code)     ← same 5-dim vector as online RL
     action = _infer_action(state, quality)  ← behavior cloning heuristic
     reward = quality_score / 5.0            ← normalised to [0, 1]
3. Push all (s, a, r, s'=terminal, done=True) into the RLAgent replay buffer.
4. Run n_steps of DQN training (uses same train_step() as online path).
5. Save updated weights.

Behavior Cloning Heuristic (action inference)
---------------------------------------------
Without a stored prompt_variant per DB row, we infer the best action from the
code's structural features:

  - Long code (ruby_len > 0.5) or many methods (num_methods > 0.3):
      → v3_examples (richer prompt with worked examples)
  - Moderate complexity (has_loops or has_blocks):
      → v2_structured (structured decomposition prompt)
  - Otherwise:
      → v1_minimal (concise prompt for simple snippets)

High-quality pairs (quality_score ≥ 4) reinforce the chosen action with a
higher reward, effectively teaching the agent to replicate successful strategies.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from agent_evolution.rl_agent import RLAgent, ACTIONS, extract_state, _DEFAULT_WEIGHTS
from training_data.dataset import DatasetManager

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

_TERMINAL_STATE = [0.0] * 5
_DEFAULT_PAIR_ID = "ruby->python"

# Quality threshold for 3-agent consensus (≥ OK = 3)
DEFAULT_MIN_QUALITY = 3.0


# ── Action inference (behavior cloning heuristic) ─────────────────────────────

def _infer_action(state: list[float]) -> int:
    """
    Map a state vector to a prompt-variant action index.

    Rules (in priority order):
      1. Long or method-heavy code → v3_examples
      2. Looping / block-heavy code → v2_structured
      3. Everything else           → v1_minimal
    """
    ruby_len_norm   = state[0]
    num_methods_norm = state[1]
    has_loops       = state[3]
    has_blocks      = state[4]

    if ruby_len_norm > 0.5 or num_methods_norm > 0.3:
        return ACTIONS.index("v3_examples")
    if has_loops or has_blocks:
        return ACTIONS.index("v2_structured")
    return ACTIONS.index("v1_minimal")


def _pair_to_experience(row: dict) -> tuple | None:
    """Convert one DB row to an RL experience tuple, or None if unusable."""
    source_code = row.get("source_code", "")
    quality_score = float(row.get("quality_score") or 0.0)

    if not source_code:
        return None

    state = extract_state(source_code)
    action = _infer_action(state)
    reward = quality_score / 5.0   # normalise to [0, 1]

    return state, action, reward, _TERMINAL_STATE, True


# ── Main offline training function ────────────────────────────────────────────

def train_from_db(
    rl_agent: RLAgent,
    dataset_manager: Optional[DatasetManager] = None,
    pair_id: str = _DEFAULT_PAIR_ID,
    min_quality: float = DEFAULT_MIN_QUALITY,
    n_steps: int = 300,
    verbose: bool = True,
) -> dict:
    """
    Load accepted training pairs from DB and run offline DQN training.

    Parameters
    ----------
    rl_agent         : RLAgent to train (weights updated in-place + saved)
    dataset_manager  : DatasetManager instance (created from env if None)
    pair_id          : language pair key, e.g. 'ruby->python'
    min_quality      : minimum quality_score to include (default: 3.0 = OK)
    n_steps          : gradient steps to run after loading data
    verbose          : print progress to stdout

    Returns
    -------
    dict with training statistics
    """
    dm = dataset_manager or DatasetManager()

    # Fetch accepted pairs from DB
    try:
        rows = dm.fetch_accepted(pair_id, limit=2000)
    except Exception as exc:
        log.error("DB fetch failed: %s", exc)
        return {"error": str(exc), "gradient_steps": 0}

    # Apply quality filter (3-agent consensus: score >= min_quality)
    filtered = [r for r in rows if float(r.get("quality_score") or 0.0) >= min_quality]

    pushed = 0
    skipped = 0

    for row in filtered:
        exp = _pair_to_experience(row)
        if exp is None:
            skipped += 1
            continue
        rl_agent.push_experience(*exp)
        pushed += 1

    if verbose:
        print(f"[OfflineTrainer] DB rows fetched:   {len(rows)}")
        print(f"[OfflineTrainer] After quality filter ({min_quality}): {len(filtered)}")
        print(f"[OfflineTrainer] Pushed to buffer:  {pushed}  (skipped: {skipped})")

    losses = rl_agent.train_n_steps(n_steps)

    if verbose:
        if losses:
            print(f"[OfflineTrainer] {len(losses)} gradient steps. "
                  f"Final loss: {losses[-1]:.6f}  ε={rl_agent.epsilon:.4f}")
        else:
            print(f"[OfflineTrainer] Not enough data for training "
                  f"(buffer: {len(rl_agent._buffer)}, need ≥ 32).")

    rl_agent.save()
    if verbose:
        print(f"[OfflineTrainer] Weights saved → {rl_agent.weights_path}")

    return {
        "source":              "db",
        "pair_id":             pair_id,
        "rows_fetched":        len(rows),
        "rows_after_filter":   len(filtered),
        "experiences_pushed":  pushed,
        "experiences_skipped": skipped,
        "gradient_steps":      len(losses),
        "final_loss":          losses[-1] if losses else None,
        "epsilon":             rl_agent.epsilon,
        "buffer_size":         len(rl_agent._buffer),
    }
