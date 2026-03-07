# Delivery Agent – Die Dunkle Fabrik

Orchestriert vollständige Code-Migrations-Aufträge – von der Analyse bis zur Auslieferung.

## Architektur

```
POST /delivery/start
        │
        ▼
DeliveryOrchestrator.create_job()
        │
        ├── Phase 1: ASSESSMENT
        │     └── AssessmentAgent analysiert Quellprojekt
        │
        ├── Phase 2: PLANNING
        │     └── CTOAgent erstellt Migrations-Plan
        │
        ├── Phase 3: EXECUTING
        │     ├── ResourceManager.check_quota() → Kontingent prüfen
        │     └── AgentSwarm führt Konvertierung durch
        │
        ├── Phase 4: VALIDATING
        │     └── QualityGate prüft: Score, Tokens, Fehler
        │           ├── OK  → status = done
        │           └── NOK → Retry (max 2x) → failed
        │
        └── delivery_jobs (Supabase) ← persistiert alle Phasen
```

## Phasen

| Status | Beschreibung |
|--------|-------------|
| `pending` | Job erstellt, wartet auf Start |
| `assessment` | Projekt-Analyse (Dateien, Komplexität, Sprache) |
| `planning` | CTO-Agent erstellt priorisierten Migrations-Plan |
| `executing` | Agenten-Schwarm führt Konvertierung durch |
| `validating` | QualityGate prüft Ergebnisse |
| `done` | Erfolgreich abgeschlossen |
| `failed` | Fehlgeschlagen (nach max. Retries) |
| `cancelled` | Manuell abgebrochen |

## Module

### `orchestrator.py`
- `DeliveryOrchestrator` – Haupt-Workflow-Engine
- `DeliveryJob` – Datenhaltung, Logging, Serialisierung
- `get_job(id)` / `list_jobs(customer_id)` – Job-Abfrage
- In-Memory-Fallback wenn Supabase nicht erreichbar

### `resource_manager.py`
- `DeliveryResourceManager` – Thread-safe Kontingent-Verwaltung
- Limits: `max_parallel_jobs` und `monthly_token_budget` pro Kunde
- Konfigurierbar über `tenants.settings` in Supabase

### `quality_gate.py`
- `QualityGate.validate(job)` → `QualityResult`
- Checks: Execution abgeschlossen, kein kritischer Fehler, Score ≥ 0.5, Token-Budget
- Bei Fehlschlag: Orchestrator startet Retry (max 2x)

### `client_portal.py`
- `get_job_status(job_id)` – öffentliche Status-Abfrage
- Sensible Interna (Plandetails) werden gefiltert
- HTML-Dashboard: `frontend/delivery.html`

## API-Endpunkte

### `POST /delivery/start`
Startet einen neuen Migrations-Auftrag.

**Auth:** `X-Api-Key` (Tenant-Key)

**Body:**
```json
{
  "description": "Migriere Ruby-on-Rails-App von github.com/... nach Django",
  "customer_id": "uuid-..."
}
```

**Response:**
```json
{
  "job_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "pending",
  "message": "Job started. Poll GET /delivery/{job_id} for status."
}
```

### `GET /delivery/{job_id}`
Öffentlicher Status-Endpunkt (API-Key erforderlich).

**Response:**
```json
{
  "job_id": "...",
  "status": "executing",
  "status_label": "⚙️  Ausführung",
  "current_phase": "executing",
  "progress": 60,
  "progress_bar": "[████████████░░░░░░░░] 60%",
  "started_at": "2026-03-06T10:00:00",
  "completed_at": "",
  "recent_logs": [
    "[10:00:01] Phase started: assessment",
    "[10:00:03] Assessment done",
    "[10:00:05] Plan ready: 4 steps",
    "[10:00:06] Executing step 1/4: Convert Ruby classes to Python"
  ]
}
```

### `POST /delivery/{job_id}/cancel`
Bricht einen laufenden Job ab. **Admin-Auth erforderlich.**

## Datenbank-Migration

```sql
CREATE TABLE IF NOT EXISTS delivery_jobs (
  id            TEXT PRIMARY KEY,
  customer_id   UUID NOT NULL,
  plan          JSONB NOT NULL DEFAULT '{}',
  status        TEXT DEFAULT 'pending',
  current_phase TEXT,
  progress      INTEGER DEFAULT 0,
  logs          TEXT[],
  started_at    TIMESTAMP,
  completed_at  TIMESTAMP,
  result_path   TEXT,
  created_at    TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_delivery_jobs_customer ON delivery_jobs(customer_id);
CREATE INDEX idx_delivery_jobs_status   ON delivery_jobs(status);
```

## Resource-Limits (konfigurierbar in `tenants.settings`)

| Einstellung | Standard | Beschreibung |
|-------------|----------|-------------|
| `max_parallel_jobs` | 3 | Max. gleichzeitige Jobs pro Kunde |
| `token_quota` | 10.000.000 | Monatliches Token-Budget |

## QualityGate-Schwellwerte

| Check | Schwellwert | Aktion bei Fehler |
|-------|------------|-------------------|
| `execution_completed` | mind. 1 Schritt | Retry |
| `no_critical_errors` | keine Error-Keywords in Logs | Retry |
| `score_threshold` | ≥ 0.5 | Retry |
| `within_token_budget` | ≤ 500.000 Token/Job | Retry / Failed |

## Tests

```bash
cd backend
pytest tests/test_delivery_agent.py -v
# 28 Tests: Lifecycle, QualityGate, ResourceManager, ClientPortal, Retry, Cancel
```

## Frontend

`frontend/delivery.html` – Self-Service-Portal für Kunden:
- Job-Status live abfragen (mit Auto-Refresh alle 10 s)
- Neuen Auftrag starten
- Fortschrittsbalken und Log-Viewer

URL: `https://yondem-production.up.railway.app/frontend/delivery.html`
