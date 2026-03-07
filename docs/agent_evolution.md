# Agent Evolution – Reinforcement Learning Layer

## Overview

`backend/agent_evolution/` adds a Deep Q-Network (DQN) layer on top of the
agent_swarm package. The goal is to have agents automatically learn which
prompt variant produces the best conversion quality for each type of Ruby code,
improving over time purely from their own experience.

## Architecture

```
SwarmMemory (JSON)
      │  conversion records (score, variant, ruby_len, …)
      ▼
  Trainer.train_from_memory()
      │  pushes (s, a, r, s') tuples into ReplayBuffer
      ▼
  RLAgent.train_n_steps(N)           ← DQN gradient steps
      │  updates _policy_net weights
      ▼
  RLAgent.best_variant(ruby_code)    ← greedy inference
      │  returns "v1_minimal" | "v2_structured" | "v3_examples"
      ▼
  Orchestrator.convert_one()         ← passes variant override
      │  to GenerationAgent via task["_rl_variant"]
      ▼
  EvaluationAgent scores output → new experience pushed back to RLAgent
```

## State Space (5 features)

| Index | Feature      | Normalisation       |
|-------|--------------|---------------------|
| 0     | ruby_len     | len / 2000 (clamp 1)|
| 1     | num_methods  | count("def ") / 20  |
| 2     | num_classes  | count("class ") / 10|
| 3     | has_loops    | 1 if .each/while/for|
| 4     | has_blocks   | 1 if "do \|" present|

All features are clamped to [0, 1].

## Action Space (3 actions)

| Index | Variant         | Description                              |
|-------|-----------------|------------------------------------------|
| 0     | v1_minimal      | Terse system prompt, minimal constraints |
| 1     | v2_structured   | Expert-engineer framing, strict rules    |
| 2     | v3_examples     | Enumerated rules, idiom replacements     |

## Neural Network

```
Input  (5)  →  Linear(5→32)  →  ReLU
           →  Linear(32→16) →  ReLU
           →  Linear(16→3)  →  Q-values per action
```

Trained with:
- **Loss**: Huber / Smooth-L1 (robust to outliers)
- **Optimizer**: Adam (lr=1e-3)
- **Discount**: γ=0.9 (short-horizon, episode = one conversion)
- **Target network**: synced every 50 steps
- **Gradient clipping**: max_norm=1.0

## Experience Replay

- Buffer capacity: 2 000 transitions
- Batch size: 32
- Minimum buffer fill before training: 32 samples

## Epsilon Schedule

| Phase          | Value       |
|----------------|-------------|
| Start          | 1.0 (random)|
| Decay per step | × 0.995     |
| Minimum        | 0.05        |

After ~200 training steps epsilon falls below 0.10, meaning >90% of decisions
are exploitation-based.

## Training

### CLI (one-shot)

```bash
cd backend
python -m agent_evolution.trainer [--steps 500] [--dry-run]
```

### Scheduled (daily, via APScheduler)

```python
# In backend/app/main.py lifespan:
from agent_evolution.trainer import schedule_daily
schedule_daily(_scheduler, _swarm_memory)
```

### From code

```python
from agent_evolution import RLAgent, train_from_memory
from agent_swarm import SwarmMemory

memory = SwarmMemory()
agent  = RLAgent()
result = train_from_memory(memory, agent, n_steps=500)
print(result)
# {'experiences_loaded': 47, 'gradient_steps': 500, 'final_loss': 0.0023, …}
```

## Orchestrator Integration

Pass an `RLAgent` instance to the `Orchestrator` constructor:

```python
from agent_swarm import Orchestrator, SwarmMemory
from agent_evolution import RLAgent

memory = SwarmMemory()
rl     = RLAgent()          # loads weights from rl_weights.pt if present

orch = Orchestrator(memory, workers=5, rl_agent=rl)
result = await orch.convert_one("legacy.rb", ruby_source)
# The RL agent chose the prompt variant; the score is fed back immediately.
```

When `rl_agent` is `None` (default), the Orchestrator falls back to the
epsilon-greedy selection in `GenerationAgent` (existing behaviour).

## Persistence

Weights are saved as `backend/agent_evolution/rl_weights.pt` (PyTorch checkpoint).
The file contains:
- `policy_state` – policy network weights
- `target_state` – target network weights
- `epsilon`      – current exploration rate
- `step`         – total gradient steps taken

The file is excluded from git (add to `.gitignore` if needed) because it
changes every training run.

## Tests

```bash
cd backend
python -m pytest tests/test_rl_agent.py -v
# 30 tests: state extraction, action space, DQN training, save/load, trainer
```

Key test cases:
- `test_q_values_change_after_training` – proves the network actually learns
- `test_epsilon_decays_during_training` – verifies exploration schedule
- `test_save_and_reload` – confirms checkpoint round-trip

---

## Automatic Prompt Optimisation (TAB 15)

### Overview

`agent_evolution/prompt_optimizer.py` wraps the Thompson-Sampling engine from
`agent_swarm/prompt_optimizer.py` with APScheduler integration and per-run
logging back into SwarmMemory.

```
SwarmMemory (prompt_variants stats)
        │
        ▼
EvolutionPromptOptimizer
        │
        ├── select_variant()          ← Thompson Sampling (Beta posterior)
        │     Beta(successes+1, failures+1) drawn per variant → argmax wins
        │
        ├── mutate_prompt(variant)    ← Synonym/structure mutations
        │     Applies MUTATIONS list (10 predefined replacements).
        │     Falls back to EXPLORATION_SUFFIX if no match found.
        │
        └── run_optimization_cycle()  ← Weekly scheduler job (Sunday 03:00 UTC)
              1. Score all variants via Thompson Sampling
              2. Identify worst_cutoff=25% worst performers
              3. Mutate champion → replace worst variants
              4. Log result to SwarmMemory.run_summaries
```

### Selection Strategy (GenerationAgent)

Three-tier layered selection:

| Priority | Condition | Action |
|----------|-----------|--------|
| 1 | `unseen variants exist` AND `rand < 0.05` (NOVEL_EPSILON) | Force exploration of untested mutation |
| 2 | Default | Thompson Sampling across full variant pool |
| 3 | Fallback | Epsilon-greedy (ε=10%) on base variants |

### Mutation Rules

| Original | Replacement |
|----------|-------------|
| `Output only` | `Return only` |
| `expert software engineer` | `senior software engineer` |
| `idiomatic Python 3` | `clean, idiomatic Python 3` |
| `No explanation` | `No prose, no explanation` |
| `Convert the given Ruby code` | `Translate the provided Ruby code` |
| *(10 rules total)* | |

If no rule matches, `EXPLORATION_SUFFIX` is appended to create a minimal variant.

### APScheduler Integration

```python
# In backend/app/main.py lifespan:
from agent_evolution.prompt_optimizer import schedule_weekly
schedule_weekly(_scheduler, _swarm_memory)
```

Job runs every **Sunday at 03:00 UTC**. Manual trigger:

```
POST /evolution/optimize
X-Admin-Key: <ADMIN_API_KEY>
```

Response:
```json
{
  "status": "ok",
  "variants_total": 4,
  "added": ["v1_minimal_mut_a3f2"],
  "removed": ["v2_structured"],
  "variants": ["v1_minimal", "v3_examples", "v1_minimal_mut_a3f2"]
}
```

### Tests

```bash
cd backend
python -m pytest tests/test_prompt_optimizer.py -v
# 11 tests: Thompson Sampling distribution, mutation, full cycle
```

---

## Limitations & Next Steps

1. **Approximate state**: `ruby_len` is stored in SwarmMemory, but
   `num_methods`, `num_classes`, `has_loops`, `has_blocks` are currently set
   to 0 during offline training (the raw source is not persisted). Store
   `extract_state()` output alongside each conversion record to fix this.

2. **Episode structure**: Each conversion is treated as a one-step episode
   (done=True, next_state=zeros). A multi-step formulation (e.g. generate →
   evaluate → re-generate on failure) would enable longer credit assignment.

3. **Model expansion**: The 3-action space can be extended to include model
   selection (NVIDIA vs DeepSeek) and temperature as continuous parameters
   (switch to Actor-Critic or PPO for continuous action spaces).

4. **Online training during swarm runs**: Currently the RL agent is only
   trained by the `Trainer`. Hook `rl_agent.train_step()` into the Orchestrator
   worker loop for truly online learning.
