# TokenBroker – Projektzusammenfassung

**Generiert:** 2026-03-07 | **Version:** TAB 14

## Was ist TokenBroker?

TokenBroker ist eine KI-Token-Vermittlungsplattform, die Nutzern ermöglicht, AI-API-Zugang guenstig zu buendeln (Group Buys) und ueber einen intelligenten Proxy-Router an die guenstigsten Provider weitergeleitet zu werden.

**Live-URL:** https://yondem-production.up.railway.app

---

## Kern-Features

| Feature | Status | Endpunkt |
|---------|--------|----------|
| Proxy-Chat mit Fallback | Aktiv | `POST /chat`, `POST /v1/chat/completions` |
| Group Buys (Crowdfunding) | Aktiv | `POST /group-buys`, `POST /group-buys/{id}/join` |
| Stripe-Zahlungen | Aktiv | `POST /payment/create-intent`, `POST /payment/webhook/stripe` |
| Token-Usage-Tracking | Aktiv | `GET /usage/{user_id}` |
| Multi-Tenant | Aktiv | `/tenant/*` |
| Agent Swarm (Ruby→Python) | Aktiv | `POST /swarm/train`, `POST /swarm/convert` |
| Market Intelligence | Aktiv | `GET /market/analysis` |
| Self-Evolution / A/B-Tests | Aktiv | `GET /evolution/*` |

---

## Provider-Kaskade

```
Anfrage → NVIDIA (free-tier, meta/llama-3.1-70b)
        → DeepSeek (Fallback, $0.14/$0.28 per 1M tokens)
```

---

## Abgeschlossene Entwicklungs-Tabs

| Tab | Commit | Feature |
|-----|--------|---------|
| TAB 1 | `9370ba0` | Discord-Logging im /chat Endpunkt |
| TAB A | `c7d5ca5` | DeepSeek-Fallback + Tests |
| TAB B | `21bcd95` | CI-Workflow (GitHub Actions) |
| TAB C | `34c4e53` | README + CI-Badge |
| TAB D | `d48f9d6` | DB-Providers: Supabase-Router + Tests |
| TAB E | `796a997` | Auth: X-TokenBroker-Key Header |
| TAB G | `67f4ea1` | MVP 2: Crowdfunding-Grundgeruest |
| TAB H | `a81215a` | Crowdfunding-API-Endpunkte |
| TAB 3 | `113c34e` | OpenAI-compat /v1/chat/completions |
| TAB 4 | `aba950e` | Frontend + Stripe Elements |
| TAB 5 | `c91f5c7` | Stripe-Zahlungsendpunkte |
| TAB 6 | `d85bcfc` | Token-Optimierung + Cache |
| TAB 7 | `4f4d2d5` | Monitoring-Dashboard |
| TAB 9 | `db0220f` | Multi-Sprachen-Training-Pipeline |
| TAB 10 | `e85c3fb` | Self-evaluierendes Agenten-System |
| TAB 14 | aktuell | Zero-Cost-Onboarding |

---

## Technologie-Stack

- **Backend:** FastAPI (Python 3.11+), APScheduler, Pydantic v2
- **Datenbank:** Supabase (PostgreSQL)
- **Payments:** Stripe
- **Auth:** X-TokenBroker-Key Header, Admin-Key
- **Notifications:** Discord Webhook
- **Deployment:** Railway (Docker/Procfile)
- **CI:** GitHub Actions
- **Tests:** pytest
