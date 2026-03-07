# TokenBroker – Vollstaendiger Projektkontext

**Fuer neue Claude-Code-Instanzen und Entwickler**

---

## Architektur-Uebersicht

```
frontend/
  index.html              # Vanilla-JS Frontend mit Stripe Elements

backend/
  app/
    main.py               # FastAPI App, alle Endpunkte, Lifespan-Scheduler
    router.py             # Provider-Routing (cheapest-first + Fallback)
    providers.py          # Provider-Definitionen (NVIDIA, DeepSeek)
    db_providers.py       # Supabase-gestuetzte Provider-Liste
    db.py                 # Supabase-Client (Singleton)
    auth.py               # API-Key-Validierung (User + Admin)
    usage.py              # Token-Usage-Logging und -Abfrage
    crowdfunding.py       # Group-Buy-Logik (create, join, check)
    trigger.py            # Automatische Group-Buy-Ausfuehrung
    payment.py            # Stripe PaymentIntent + Webhook
    discord.py            # Discord-Webhook-Benachrichtigungen
    metrics.py            # In-Memory-Fehlerrate-Tracking
    tenant/               # Multi-Tenant-Isolation + Resource-Manager

  agent_swarm/            # Ruby→Python-Konverter (parallele Worker)
  market_intelligence/    # Competitor-Tracking, Trend-Analyse, Opportunities
  evolution/              # A/B-Testing, Auto-Optimierung, Version-Control
  onboarding/             # Kontext-Generator und Onboarding-Utilities
  tests/                  # pytest-Testsuiten fuer alle Module

docs/
  onboarding/             # Dieser Ordner
  payment.md              # Stripe-Integrationsplan
  monitoring.md           # Monitoring-Konzept
  mvp3.md                 # MVP-3-Planung (Vergleichsplattform)
  token_optimization.md   # Cache + Optimierungs-Doku
  agent_swarm.md          # Swarm-Architektur-Beschreibung
```

---

## Wichtige Architektur-Entscheidungen

### 1. Provider-Fallback-Kette
- Primär: NVIDIA (kostenlos, Free-Tier)
- Fallback: DeepSeek (guenstig, $0.14/$0.28)
- Erweiterbar: neue Provider in `providers.py` eintragen, DB-Eintrag in Supabase

### 2. Auth-System
- **User-Auth:** `X-TokenBroker-Key` Header → Supabase-Lookup → `user_id`
- **Admin-Auth:** `X-Admin-Key` Header → Env-Variable-Vergleich
- **OpenAI-compat:** Bearer-Token in Authorization-Header

### 3. Group-Buy-Flow
```
1. create_group_buy() → Status: "pending"
2. join_group_buy() → Participant wird hinzugefuegt
3. check_and_trigger() → Wenn current_tokens >= target_tokens → "active"
4. process_completed_group_buys() → Laeuft alle 5 Min per APScheduler
```

### 4. Deployment
- **Platform:** Railway
- **Config:** `railway.toml`, `Procfile`
- **Docker:** `Dockerfile` im Root
- **Env-Vars:** Alle Secrets in Railway-Dashboard (NICHT in .env committen)

### 5. Datenbank-Schema (Supabase)
```sql
users (id, api_key, created_at)
token_usage (id, user_id, tokens_used, provider, timestamp)
group_buys (id, name, target_tokens, current_tokens, price_per_token, provider, status, expires_at)
group_buy_participants (id, group_buy_id, user_id, tokens_ordered, paid, created_at)
providers (id, name, model, active, input_price_per_million, output_price_per_million)
```

---

## Umgebungsvariablen (alle benoetigt)

| Variable | Zweck | Wo setzen |
|----------|-------|-----------|
| `NVIDIA_API_KEY` | NVIDIA AI-Provider | Railway |
| `DEEPSEEK_API_KEY` | DeepSeek-Provider | Railway |
| `SUPABASE_URL` | DB-Verbindung | Railway |
| `SUPABASE_KEY` | DB-Auth | Railway |
| `DISCORD_WEBHOOK_URL` | Benachrichtigungen | Railway |
| `ADMIN_API_KEY` | Admin-Endpunkte | Railway |
| `TOKEN_LIMIT_DEFAULT` | User-Token-Limit (default: 1000000) | Railway |
| `STRIPE_SECRET_KEY` | Stripe-Payments | Railway (ausstehend) |
| `STRIPE_PUBLISHABLE_KEY` | Stripe Frontend | Railway (ausstehend) |
| `STRIPE_WEBHOOK_SECRET` | Stripe-Webhook-Validierung | Railway (ausstehend) |

---

## Lokale Entwicklung

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# .env mit NVIDIA_API_KEY, DEEPSEEK_API_KEY, SUPABASE_URL, SUPABASE_KEY anlegen
uvicorn app.main:app --reload

# Tests
cd backend && pytest tests/ -v
```

---

## CI/CD

- **GitHub Actions:** `.github/workflows/ci.yml` – laeuft bei jedem Push
- **Railway:** Automatisches Deployment bei Push auf `main`
- **Discord:** Benachrichtigung nach jedem erfolgreichen Chat-Call

---

## Coding-Konventionen

- FastAPI + Pydantic v2 fuer alle Endpunkte
- `async def` fuer I/O-gebundene Endpunkte, `def` fuer CPU/DB
- Tests mit pytest, Fixtures in `conftest.py` (falls vorhanden)
- Commit-Format: `[TAB X] Kurzbeschreibung`
- Keine Secrets in Code oder Git
