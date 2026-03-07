# CTO Agent – Architektur-Dokumentation

## Übersicht

Der CTO-Agent ist die zentrale Entscheidungs- und Aufsichtsinstanz für alle Agenten im TokenBroker-System. Er überwacht Architekturentscheidungen, validiert Vorschläge anderer Agenten gegen gespeicherte Regeln und koordiniert den Agenten-Schwarm.

```
┌──────────────────────────────────────────────────────┐
│                   CTO Agent                          │
│  ┌───────────┐  ┌───────────┐  ┌──────────────────┐ │
│  │ Planner   │  │ Validator │  │ LessonsManager   │ │
│  │(todo.md)  │  │(rules)    │  │(lessons.md)      │ │
│  └─────┬─────┘  └─────┬─────┘  └────────┬─────────┘ │
└────────┼──────────────┼─────────────────┼───────────┘
         │              │                 │
         ▼              ▼                 ▼
┌──────────────────────────────────────────────────────┐
│           CTOOrchestrator                            │
│   (wraps SwarmOrchestrator with CTO pre-approval)   │
└──────────────────┬───────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────┐
│           SwarmOrchestrator                          │
│   GenerationAgent × N  +  EvaluationAgent × N       │
└──────────────────────────────────────────────────────┘
```

## Module

### `core.py` – CTOAgent

Lädt den Projektkontext und bietet die zentrale `decide()`-API:

```python
from cto_agent import CTOAgent

cto = CTOAgent()
decision = cto.decide(
    "Migrate to Redis caching",
    context={"token_cost_increase_pct": 5.0, "provider": "nvidia"}
)
print(decision.approved)   # True/False
print(decision.rationale)  # Begründung
```

Geladene Kontext-Dateien:
| Datei | Pflicht | Inhalt |
|---|---|---|
| `project_config.yaml` | nein | Maschinenlesbare Schwellwerte und Constraints |
| `PROJECT_CONTEXT.md` | nein | Architektur-Narrativ |
| `tasks/lessons.md` | nein | Akkumulierte Regeln und Erkenntnisse |
| `NEXT_SESSION.md` | nein | Offene Aufgaben und Deployment-Zustand |

### `validator.py` – RuleEngine + Validator

Die Regel-Engine extrahiert `RULE:`-Zeilen aus `lessons.md`:

```
RULE: token_cost_increase > 20% → reject
RULE: success_rate < 70% → alert
RULE: provider == "unknown" → reject
```

Unterstützte Aktionen:
- `reject` / `block` → Proposal wird abgelehnt (Violation)
- `alert` / `warn` → Nur Warnung, kein Reject

Hard Constraints aus `project_config.yaml`:
- `token_cost_increase_limit` (default: 20%)
- `min_success_rate` (default: 70%)
- `preferred_providers` (default: nvidia, deepseek)
- `architecture_constraints` (Stichwörter, die im Proposal nicht vorkommen dürfen)

### `planner.py` – Planner

Liest `NEXT_SESSION.md` und generiert `tasks/todo.md` mit Prioritäten:

```
## Priority 1 – Critical
- [ ] Fix critical bug in payment endpoint  [dep: none]

## Priority 2 – Important
- [ ] Improve test coverage for agent swarm

## Priority 3 – Nice-to-have
- [ ] Optional: cleanup legacy comments
```

Prioritäts-Inferenz anhand von Schlüsselwörtern:
| Schlüsselwort | Priorität |
|---|---|
| critical, bug, fix, security | 1 |
| feature, improve, refactor, test | 2 |
| doc, optional, cleanup, nice | 3 |

### `lessons.py` – LessonsManager

Pflegt `tasks/lessons.md` mit Erkenntnissen und Regeln:

```python
mgr = LessonsManager(Path("tasks/lessons.md"))
mgr.add_insight("DeepSeek fallback reduced cost by 35%")
mgr.add_rule("latency > 30s → alert")
new_rules = mgr.derive_rules_from_insights()  # automatische Regelableitung
```

### `orchestrator.py` – CTOOrchestrator

Wrapper um den bestehenden `SwarmOrchestrator`. Jede Datei wird vor der Konvertierung vom CTO-Agenten geprüft:

```python
cto_orch = CTOOrchestrator(workers=5)
summary = asyncio.run(cto_orch.train(Path("ruby_files/")))
print(summary["cto_rejected"])  # abgelehnte Dateien
```

## API-Endpunkte

| Method | Endpoint | Auth | Beschreibung |
|---|---|---|---|
| `POST` | `/cto/plan` | Admin | Generiert `tasks/todo.md` aus `NEXT_SESSION.md` |
| `POST` | `/cto/decide` | Admin | Validiert einen Vorschlag gegen Regeln |
| `GET` | `/cto/status` | Admin | CTO-Agent-Zusammenfassung (Regeln, Config) |

### `POST /cto/plan`

```json
{ "force": false }
```

Response:
```json
{
  "status": "generated",
  "total_tasks": 12,
  "by_priority": {"1": 3, "2": 6, "3": 3},
  "output_path": "/path/to/tasks/todo.md",
  "generated_at": "2026-03-07T10:00:00"
}
```

### `POST /cto/decide`

```json
{
  "proposal": "Switch all requests to GPT-4",
  "context": {
    "token_cost_increase_pct": 340.0,
    "provider": "openai"
  }
}
```

Response:
```json
{
  "approved": false,
  "rationale": "Rejected: Token cost increase 340.0% exceeds limit 20%; Provider 'openai' not in preferred list",
  "violations": [
    "Token cost increase 340.0% exceeds limit 20%",
    "Provider 'openai' not in preferred list ['nvidia', 'deepseek']"
  ]
}
```

## `project_config.yaml` – Konfigurationsreferenz

```yaml
token_cost_increase_limit: 0.20   # 20% – über diesem Wert: reject
min_success_rate: 0.70            # 70% – unter diesem Wert: reject
max_batch_size: 50
preferred_providers:
  - nvidia
  - deepseek
architecture_constraints:
  - monolith                       # darf im Proposal nicht vorkommen
  - synchronous_only
```

## Integration mit bestehenden Agenten (TAB 24–26)

Der CTO-Agent ist als **übergeordnete Instanz** konzipiert. Bestehende Agenten sollen ihn als Entscheidungsquelle nutzen:

```python
# Beispiel: Bug-Fixer-Agent (TAB 25) fragt CTO vor dem Fix
from cto_agent import CTOAgent

cto = CTOAgent()
decision = cto.decide(
    f"Apply hotfix to {filename}",
    context={"success_rate": agent_stats["success_rate"]}
)
if not decision.approved:
    log_rejection(filename, decision.rationale)
    return
# ... proceed with fix
```

## Deployment

Der CTO-Agent benötigt keine eigenen Env-Variablen – er liest ausschließlich lokale Dateien.

Optional: `project_config.yaml` im Repo-Root erstellen, um Regeln anzupassen.

---

_Dokumentiert für TAB 27 – implementiert mit Claude Sonnet 4.6_
