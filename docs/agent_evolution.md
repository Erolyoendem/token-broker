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
