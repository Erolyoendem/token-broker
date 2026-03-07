# Assessment Agent – Automatisierte Big-4-Statusanalyse

## Uebersicht

`backend/assessment_agent/` automatisiert die erste Phase einer Unternehmensberatung:
die Analyse des technischen Status quo. In Minuten statt Wochen liefert der Agent
einen strukturierten Bericht im Stil einer Big-4-Praesentation.

---

## Architektur

```
POST /assessment/run
        │
        ▼
  CodeScanner               – LOC, Sprachen, Frameworks
        │
        ▼
  AssessmentDependencyAnalyzer – Abhaengigkeitsgraph, Pain Points
        │
        ▼
  TechDebtEstimator         – Score 0-100 in 7 Kategorien
        │
        ▼
  ReportGenerator           – LLM-Bericht (Executive Summary + Empfehlungen)
        │
        ▼
  Supabase: assessments     – Persistierung des Ergebnisses
        │
        ▼
  docs/assessment/*.md      – Markdown-Bericht
```

---

## Module

### `code_scanner.py` – Projektstruktur-Analyse

Scannt rekursiv alle Quelldateien und erkennt:

| Feature | Details |
|---------|---------|
| LOC pro Sprache | Python, Ruby, JS/TS, Java, Go, SQL, ... |
| Dateien pro Sprache | Absolut und prozentual |
| Frameworks | Rails, Django, FastAPI, Flask, Express, Next.js, Spring |
| Groesste Dateien | Top-10 nach Bytegroeße |

**Erkannte Sprachen:** `.py`, `.rb`, `.js`, `.ts`, `.tsx`, `.java`, `.go`, `.rs`, `.php`, `.cs`, `.sql`, `.yaml`, `.html`, `.css`, `.sh`, `.md`

**Übersprungene Verzeichnisse:** `.git`, `node_modules`, `__pycache__`, `venv`, `dist`, `build`, `vendor`

---

### `dependency_analyzer.py` – Abhaengigkeitsgraph + Pain Points

Erweiterung von `enterprise_migration.DependencyAnalyzer` um sprachuebergreifende Analyse:

**Unterstuetzte Sprachen:**
- **Ruby:** via `enterprise_migration.DependencyAnalyzer` (`require`, `require_relative`, `include`)
- **Python:** `from X import Y`, `import X` (relative Imports aufgeloest)
- **JavaScript/TypeScript:** `require('X')`, `import from 'X'`

**Erkannte Pain Points:**

| Kategorie | Schwere | Erkennung |
|-----------|---------|-----------|
| `circular_dependency` | critical | DFS-Zykluserkennung |
| `large_file` | medium/high | > 500 / > 2000 Zeilen |
| `high_fan_in` | medium | > 5 eingehende Abhaengigkeiten |
| `outdated_dependency` | high | Regex auf Gemfile/requirements.txt/package.json |

---

### `tech_debt_estimator.py` – Tech-Debt-Score 0-100

7 gewichtete Heuristiken:

| Kategorie | Gewicht | Erkennung |
|-----------|---------|-----------|
| `duplication` | 20% | Identische 6-Zeilen-Bloecke in versch. Dateien |
| `missing_tests` | 20% | Test-LOC-Anteil < 20% |
| `outdated_syntax` | 15% | Python-2-Syntax, `var` in JS, alte Ruby-Idiome |
| `large_files` | 15% | > 500 / > 2000 Zeilen |
| `missing_docs` | 10% | Funktionen ohne Docstring (Python) |
| `complexity` | 10% | Verschachtelungstiefe ≥ 5, Funktionen > 100 Zeilen |
| `todo_markers` | 10% | TODO / FIXME / HACK / XXX |

**Notenscala:**

| Score | Note | Bedeutung |
|-------|------|-----------|
| 0-15  | A    | Hervorragend |
| 16-30 | B    | Gut |
| 31-50 | C    | Akzeptabel |
| 51-70 | D    | Kritisch |
| 71-100| F    | Notfall |

---

### `report_generator.py` – LLM-gestuetzter Big-4-Bericht

Erstellt einen Markdown-Bericht mit:
1. **Executive Summary** – via TokenBroker-LLM-Proxy generiert
2. **Projektstruktur** – LOC, Sprachen, Frameworks, groesste Dateien
3. **Abhaengigkeitsanalyse** – Graph-Metriken, Pain-Points-Tabelle
4. **Tech-Debt-Analyse** – Score pro Kategorie, kritische Befunde
5. **Handlungsempfehlungen** – 5 priorisierte Punkte (via LLM)
6. **Naechste Schritte** – 3-Phasen-Roadmap

Bei LLM-Fehler (kein API-Key, Timeout): strukturierter Fallback-Text.

---

## API-Endpunkte

### `POST /assessment/run` (Admin)

Startet einen vollstaendigen Assessment-Lauf.

```json
{
  "project_name": "MeinProjekt",
  "path": "/absolute/pfad/zum/projekt"
}
```

**Response:**
```json
{
  "assessment_id": 1,
  "project_name": "MeinProjekt",
  "tech_debt_score": 42,
  "tech_debt_grade": "C",
  "summary": {
    "total_files": 128,
    "total_lines": 18430,
    "frameworks": ["FastAPI", "Ruby on Rails"],
    "pain_points": 7,
    "tech_debt_grade": "C"
  },
  "report_path": "docs/assessment/meinprojekt_20260307_1430.md"
}
```

### `GET /assessment/{id}` (Admin)

Gibt ein gespeichertes Assessment aus der DB zurueck.

### `GET /assessments` (Admin)

Listet die letzten 50 Assessments.

---

## Datenbank-Tabelle `assessments`

```sql
CREATE TABLE IF NOT EXISTS assessments (
  id               SERIAL PRIMARY KEY,
  project_name     TEXT NOT NULL,
  repo_url         TEXT,
  tech_debt_score  INTEGER,
  summary          JSONB,
  report_path      TEXT,
  created_at       TIMESTAMP DEFAULT NOW()
);
```

---

## Verwendung

### CLI / lokal

```python
from assessment_agent import (
    CodeScanner, AssessmentDependencyAnalyzer,
    TechDebtEstimator, ReportGenerator,
)
from pathlib import Path

root = Path("/pfad/zum/projekt")

scan      = CodeScanner(root).scan()
dep_graph = AssessmentDependencyAnalyzer(root).analyze()
debt      = TechDebtEstimator(root).estimate()

print(f"Tech-Debt Score: {debt.total_score}/100 (Note: {debt.grade})")
print(f"Pain Points: {dep_graph.summary()['pain_points']}")

report_path = ReportGenerator().generate("MeinProjekt", scan, dep_graph, debt)
print(f"Bericht: {report_path}")
```

### Via API (curl)

```bash
curl -X POST https://yondem-production.up.railway.app/assessment/run \
  -H "x-admin-key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"project_name": "MeinProjekt", "path": "/app"}'
```

---

## Tests

```bash
cd backend
python -m pytest tests/test_assessment_agent.py -v
# 35 Tests: CodeScanner, DependencyAnalyzer, TechDebtEstimator, ReportGenerator, API
```

**Testabdeckung:**
- CodeScanner: Sprach-Erkennung, Framework-Detection, LOC-Zaehlung, Leer-Projekt
- DependencyAnalyzer: Zykluserkennung, Pain-Points, leeres Projekt
- TechDebtEstimator: alle 7 Kategorien, Notenscala, Grenzwerte
- ReportGenerator: LLM-Mock, Fallback, Fehlerresilienz
- API: Auth, Fehlerbehandlung, erfolgreicher Lauf (gemockt)

---

## Einschraenkungen & Erweiterungen

| Einschraenkung | Naechster Schritt |
|----------------|-------------------|
| Kein Git-Clone | `gitpython` integrieren fuer `repo_url` |
| Zirkulaere Imports nur fuer rel. Pfade | AST-basierte Analyse fuer absolut |
| Duplikations-Check langsam bei grossen Repos | Sampling oder MinHash |
| LLM-Text auf Deutsch hartkodiert | Sprache konfigurierbar machen |
