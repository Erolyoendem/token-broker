# Next Session – TokenBroker

## Deployment Status (2026-03-06)

| Feld                | Wert |
|---------------------|------|
| Deployment ID       | 3a492c8e-30fa-48c1-bdfc-7b961887666e |
| Status              | SUCCESS |
| URL                 | https://yondem-production.up.railway.app |
| Health              | `{"status":"ok","service":"TokenBroker"}` |
| Environment         | production |
| Service             | yondem |

## Env-Variablen (gesetzt)

- `DEEPSEEK_API_KEY` — gesetzt am 2026-03-06
- `DISCORD_WEBHOOK_URL` — Discord-Benachrichtigungen aktiv
- `NVIDIA_API_KEY` — vorhanden (free-tier)
- `SUPABASE_*` — DB-Verbindung aktiv

## Abgeschlossene Tabs (Git-History)

| Tag   | Commit     | Beschreibung |
|-------|------------|--------------|
| TAB 1 | `9370ba0`  | Discord-Logging im /chat Endpunkt |
| TAB A | `c7d5ca5`  | DeepSeek-Fallback + Tests |
| TAB B | `21bcd95`  | CI-Workflow (GitHub Actions) |
| TAB C | `34c4e53`  | README + CI-Badge |
| TAB D | `d48f9d6`  | DB-Providers: Supabase-Router + Tests |
| TAB E | `796a997`  | Auth: X-TokenBroker-Key Header |
| TAB G | `67f4ea1`  | MVP 2: Crowdfunding-Grundgerüst (group_buys, 4 Tests) |
| TAB H | `a81215a`  | Crowdfunding-API-Endpunkte |
| TAB 4 | *(pending)* | Payment-Doku und Frontend-Skizze |

## Provider-Konfiguration

- **NVIDIA** – meta/llama-3.1-70b-instruct – kostenlos (free-tier credits), primärer Provider
- **DeepSeek** – deepseek-chat – $0.14/$0.28 per 1M tokens, Fallback

## Offene Punkte / nächste Schritte

- Token-Limits pro User konfigurierbar machen (aktuell: `TOKEN_LIMIT_DEFAULT=1000000`)
- **Zahlungsintegration vorbereitet** – `docs/payment.md` + `frontend/index.html` angelegt;
  nächster Schritt: `backend/app/payment.py` implementieren, Migration 003 einspielen,
  Stripe-Keys (`STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`)
  in Railway-Dashboard konfigurieren
- Monitoring/Alerting ausbauen (aktuell nur Discord-Notify pro Chat-Call)
- NVIDIA free-tier Quota prüfen und ggf. kostenpflichtiges Konto hinterlegen
