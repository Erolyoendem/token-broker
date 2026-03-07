# TokenBroker – Naechste Aufgaben (priorisiert)

**Stand:** 2026-03-07

---

## Prioritaet 1 – Kritisch / Umsatz-relevant

### 1.1 Stripe-Integration abschliessen
- `backend/app/payment.py` ist implementiert, aber Railway-Secrets fehlen
- **Aktion:** `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` in Railway-Dashboard setzen
- **Dateien:** `backend/app/payment.py`, `docs/payment.md`
- **Migration 003** muss eingespielt werden (Stripe-Felder in group_buys-Tabelle)

### 1.2 Token-Limits pro User konfigurierbar machen
- Aktuell: hartkodiertes `TOKEN_LIMIT_DEFAULT=1000000` fuer alle User
- **Aktion:** Per-User-Limits in Supabase speichern, API-Endpunkt zum Setzen
- **Datei:** `backend/app/usage.py`, `backend/app/main.py`

---

## Prioritaet 2 – Stabilitaet

### 2.1 NVIDIA Free-Tier Quota pruefen
- Free-Tier-Credits koennen erschoepft sein
- **Aktion:** NVIDIA-Dashboard pruefen, ggf. kostenpflichtiges Konto anlegen
- **Env:** `NVIDIA_API_KEY`

### 2.2 Monitoring ausbauen
- Aktuell: nur Discord-Notify pro Chat-Call
- **Aktion:** Alerting bei Fehlerrate > 5%, latency > 10s
- **Datei:** `backend/app/discord.py`, `docs/monitoring.md`

---

## Prioritaet 3 – Features

### 3.1 MVP 3: Vergleichsplattform
- Konzept liegt vor in `docs/mvp3.md`
- Provider-Preisvergleich fuer Endnutzer

### 3.2 Enterprise-Tier fertigstellen
- Multi-Tenant ist implementiert (`backend/tenant/`)
- Isolation und Resource-Manager vorhanden
- Preismodell und Onboarding-Flow fehlen

### 3.3 Training-Pipeline produktionsreif machen
- Ruby→Python-Konverter funktioniert
- Qualitaets-Threshold fuer automatisches Deployment fehlt

---

## Stichwort-zu-Kontext-Mapping

| Stichwort | Relevante Dateien |
|-----------|-------------------|
| "payment" | `backend/app/payment.py`, `docs/payment.md`, `frontend/index.html` |
| "crowdfunding" | `backend/app/crowdfunding.py`, `backend/app/trigger.py` |
| "auth" | `backend/app/auth.py` |
| "providers" | `backend/app/providers.py`, `backend/app/router.py`, `backend/app/db_providers.py` |
| "evolution" | `backend/evolution/` (4 Module) |
| "swarm" | `backend/agent_swarm/`, `/swarm/convert` Endpunkt |
| "market" | `backend/market_intelligence/` (4 Module) |
| "tenant" | `backend/tenant/isolation.py`, `backend/tenant/resource_manager.py` |
| "monitoring" | `docs/monitoring.md`, `backend/app/metrics.py` |
| "Tab 8" | Kein Commit gefunden – wahrscheinlich uebersprungen |
