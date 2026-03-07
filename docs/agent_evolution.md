# Agent Evolution – Selbst-evolvierende Prompt-Optimierung

## Überblick

TokenBroker nutzt ein Reinforcement-Learning-Framework, das automatisch die
besten Prompt-Varianten für die Ruby→Python-Konvertierung findet und weiterentwickelt.

## Architektur

```
SwarmMemory (JSON)
      │
      ▼
PromptOptimizer          GenerationAgent
  Thompson Sampling  ←→  _select_variant()
  mutate_prompt()         update_variants()
  run_optimization_cycle()
      │
      ▼
APScheduler (weekly, So 03:00)
POST /evolution/optimize (manuell)
```

## Auswahlstrategie (GenerationAgent)

Dreistufig bei jeder Konvertierung:

| Stufe | Trigger | Verhalten |
|-------|---------|-----------|
| 1 | `random() < 0.05` | Erzwungene Exploration: wählt eine **nie getestete** Variante |
| 2 | Normalfall | **Thompson Sampling** via `PromptOptimizer.select_variant()` |
| 3 | Fallback | Epsilon-greedy auf `SwarmMemory` (Legacy, ε=10 %) |

## Thompson Sampling

Für jede Variante wird aus einer Beta-Verteilung gesampelt:

```
sample ~ Beta(successes + 1, failures + 1)
```

Die Variante mit dem höchsten Sample gewinnt. Varianten mit wenig Daten
haben hohe Unsicherheit → werden öfter ausprobiert (automatische Exploration).

## Mutations-Engine

`PromptOptimizer.mutate_prompt(variant_id, text)` wendet eine zufällig
gewählte Transformation aus `MUTATIONS` an:

- Synonymersetzungen ("Output only" → "Return only")
- Stiländerungen ("expert" → "senior", "strictly" → "exactly")
- Strukturvariationen ("Convert the given" → "Translate the provided")

Greift keine Regel, wird ein Exploration-Suffix angehängt.

## Wöchentlicher Optimierungszyklus

1. Alle aktiven Varianten nach Thompson-Sampling-Score sortieren.
2. Schlechteste 25 % (`worst_cutoff`) identifizieren.
3. Champion (beste Variante) mutieren → neue Variante erzeugen.
4. Schlechteste Varianten ersetzen.
5. Pool auf `max_variants=8` trimmen.

**Scheduler:** jeden Sonntag 03:00 UTC via APScheduler.
**Manuell:** `POST /evolution/optimize` (Admin-Key erforderlich).

## API

### `POST /evolution/optimize`
Löst einen Optimierungszyklus manuell aus.

**Header:** `X-Admin-Key: <ADMIN_API_KEY>`

**Response:**
```json
{
  "status": "ok",
  "variants_total": 3,
  "added": ["v1_minimal_mut_a3f2"],
  "removed": ["v2_structured"],
  "variants": ["v1_minimal", "v3_examples", "v1_minimal_mut_a3f2"]
}
```

## Tests

```bash
cd backend
pytest tests/test_prompt_optimizer.py -v
# 11 Tests: Thompson Sampling, Mutation, Optimierungszyklus
```

## Datei-Übersicht

| Datei | Zweck |
|-------|-------|
| `agent_swarm/prompt_optimizer.py` | PromptOptimizer-Klasse, Thompson Sampling, Mutations |
| `agent_swarm/generation_agent.py` | Dreistufige Auswahl, `update_variants()` |
| `agent_swarm/memory.py` | Persistenz (JSON), `prompt_stats()`, `record_prompt_result()` |
| `tests/test_prompt_optimizer.py` | 11 Unit-Tests |

---

## Offline-Training aus synthetischen Daten (TAB 20)

### Übersicht

Ergänzt das Online-Training durch Behavior Cloning aus der `training_pairs`-DB-Tabelle.

```
training_pairs (Supabase DB)
        │  quality_score ≥ 3.0 + status='accepted'
        ▼
DatasetManager.fetch_accepted()
        │
        ▼
_pair_to_experience() → (state, action, reward, s'=terminal, done=True)
        │
        ▼
RLAgent.replay_buffer  ←  auch SwarmMemory (bei combined=True)
        │
        ▼
DQN train_step() × n_steps → rl_weights.pt
```

### Action-Inferenz (Behavior Cloning)

Da keine `prompt_variant` pro DB-Zeile gespeichert ist, wird die optimale
Aktion aus dem State-Vektor abgeleitet:

| Bedingung | Aktion |
|-----------|--------|
| `ruby_len > 0.5` oder `num_methods > 0.3` | `v3_examples` |
| `has_loops` oder `has_blocks` | `v2_structured` |
| sonst | `v1_minimal` |

### Qualitätsfilter (3-Agenten-Konsens)

Nur Zeilen mit `quality_score ≥ 3.0` (= "OK"-Majority-Rating der 3 Agenten).

### Reward-Signal

`reward = quality_score / 5.0` → normalisiert auf [0, 1]

### API-Endpunkt

`POST /evolution/train-offline` (Admin-Key erforderlich)

```json
{
  "pair_id": "ruby->python",
  "min_quality": 3.0,
  "n_steps": 300,
  "combined": false
}
```

Mit `combined: true` → kombiniertes Online (SwarmMemory) + Offline (DB) Training.

### Kombiniertes Training (`train_combined`)

```python
from agent_evolution.trainer import train_combined

result = train_combined(
    memory=swarm_memory,
    rl_agent=rl_agent,
    dataset_manager=dm,
    n_steps_online=300,
    n_steps_offline=300,
)
# result["total_gradient_steps"] = online + offline steps
```

### Dateien

| Datei | Zweck |
|-------|-------|
| `agent_evolution/train_from_data.py` | Offline-Trainer: DB-Laden, Behavior Cloning |
| `agent_evolution/trainer.py` | Online + `train_combined()` |
| `agent_evolution/rl_agent.py` | DQN-Agent, State-Extraktion |
| `tests/test_offline_training.py` | 16 Unit-Tests |
