# Bug Fixer – Automatisierter 5xx-Error-Repair

`infra/bug_fixer.py` überwacht Railway-Produktions-Logs auf HTTP-5xx-Fehler,
lässt einen LLM einen Fix generieren und öffnet automatisch einen Pull-Request.

## Architektur

```
Railway Logs
     │
     ▼
fetch_recent_errors()   ← Railway CLI / API / Health-Fallback
     │
     ▼
parse_errors(log)       ← regex-basiert, Deduplizierung per Fingerprint
     │
     ▼
generate_fix(error)     ← TokenBroker LLM-Proxy (/v1/chat/completions)
     │
     ▼
apply_fix(fix)          ← Branch → Commit → PR (gh CLI)
     │
     ▼
Discord-Benachrichtigung
```

## Funktionen

### `fetch_recent_errors(lines=100) → str`

Holt die letzten `lines` Zeilen Railway-Logs. Reihenfolge der Strategien:

1. **Railway CLI** (`railway logs --tail N`) – wenn `RAILWAY_TOKEN` gesetzt
2. **Railway GraphQL-API** – wenn `RAILWAY_TOKEN` + `RAILWAY_SERVICE_ID` gesetzt
3. **Health-Fallback** – GET /health, synthetischer Log-Eintrag bei 5xx

### `parse_errors(log) → list[ParsedError]`

Scannt den Log-Text mit regulären Ausdrücken:
- erkennt `HTTP 5xx`-Zeilen
- extrahiert Methode, URL, Stacktrace (bis zu 35 Kontext-Zeilen)
- deupliziert über SHA-1-Fingerprint (`error_type:url:stacktrace[:200]`)

Felder in `ParsedError`:
| Feld | Inhalt |
|------|--------|
| `status_code` | 500, 502, 503, … |
| `url` | z.B. `/chat` |
| `method` | GET / POST / … |
| `stacktrace` | Python-Traceback oder Log-Zeile |
| `fingerprint` | Stabiler 12-Zeichen-Hash zur Deduplizierung |

### `generate_fix(error) → GeneratedFix | None`

Sendet einen strukturierten Prompt an `POST /v1/chat/completions` (eigener
TokenBroker-Proxy). Erwartet JSON-Antwort mit:
- `explanation` – Root-Cause-Analyse
- `patch` – Unified Diff oder Code-Block
- `files_changed` – betroffene Dateien
- `confidence` – `high | medium | low`

Bei `confidence=low` wird kein PR erstellt.

### `apply_fix(fix, dry_run=False) → str | None`

1. `git checkout main && git pull`
2. `git checkout -b fix/5xx-<fingerprint>-<ts>`
3. Schreibt `docs/fix_proposals/<branch>.md` mit Erklärung + Patch
4. `git commit + push`
5. `gh pr create` mit Review-Checkliste

Gibt die PR-URL zurück oder `None` bei Fehler.

> ⚠️ KI-generierte Patches landen in einem PR – **niemals auto-mergen**.
> Ein Mensch muss den Diff überprüfen bevor der Branch gemergt wird.

## GitHub Actions

Datei: `.github/workflows/bug_fixer.yml`

```yaml
on:
  schedule:
    - cron: "15 * * * *"   # stündlich
  workflow_dispatch:         # manuell + dry-run Option
```

### Benötigte GitHub Secrets

| Secret | Beschreibung |
|--------|-------------|
| `RAILWAY_TOKEN` | Railway API-Token (Settings > Tokens) |
| `RAILWAY_SERVICE_ID` | Service-ID aus Railway Dashboard |
| `TOKENBROKER_API_KEY` | Eigener API-Key für LLM-Proxy |
| `GH_TOKEN` | GitHub PAT mit `repo` + `pull_requests` Scope |
| `DISCORD_WEBHOOK_URL` | Für Fehler- und PR-Benachrichtigungen |

### Einrichten

```bash
# Im GitHub-Repository: Settings > Secrets and variables > Actions
gh secret set RAILWAY_TOKEN      --body "..."
gh secret set RAILWAY_SERVICE_ID --body "..."
gh secret set TOKENBROKER_API_KEY --body "..."
gh secret set GH_TOKEN           --body "..."
```

### Manuell ausführen (dry-run)

```bash
# Lokal
python infra/bug_fixer.py --dry-run

# GitHub Actions UI: Actions > Bug Fixer > Run workflow > dry_run=true
```

## Umgebungsvariablen (lokal)

```bash
# backend/.env
RAILWAY_TOKEN=rly_...
RAILWAY_SERVICE_ID=...
TOKENBROKER_API_KEY=tkb_...
GH_TOKEN=ghp_...
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
BUG_FIXER_MAX_FIXES=3         # max. PRs pro Lauf
```

## Fix-Proposals

Generierte Fix-Vorschläge werden unter `docs/fix_proposals/` abgelegt:

```
docs/fix_proposals/
└── fix/5xx-abc123def456-1741234567.md
```

Jede Datei enthält:
- Root-Cause-Analyse
- Unified Diff / Code-Block
- Liste betroffener Dateien
- Hinweis zur manuellen Überprüfung

GitHub Actions lädt diese als Build-Artifact hoch (14 Tage Aufbewahrung).

## Sicherheitshinweise

- Patches werden **nie automatisch gemergt** – immer als PR
- `confidence=low`-Fixes werden verworfen
- `--dry-run` Modus für Tests ohne Git-Operationen
- Der Bot-Commit enthält den Fingerprint zur Rückverfolgung
