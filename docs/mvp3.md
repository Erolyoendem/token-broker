# MVP 3 – Vergleichsplattform für Token-Anbieter

> „Verivox für KI" – Nutzer finden den günstigsten, schnellsten und zuverlässigsten KI-Token-Anbieter auf einen Blick.

---

## 1. Ziel

Nutzer vergleichen Token-Anbieter (OpenAI, Anthropic, NVIDIA, DeepSeek, Mistral u. a.) nach:

- **Preis** – Input/Output-Kosten pro 1 M Token
- **Modell** – verfügbare Modelle, Kontextfenster, Multimodalität
- **Verfügbarkeit** – Uptime, Latenz (p50/p95), Rate-Limits
- **Qualität** – Benchmark-Scores (MMLU, HumanEval), Community-Ratings
- **Zahlungsmodell** – Pay-as-you-go vs. Abo vs. Free-Tier

Zielgruppe: Entwickler, Startups, Unternehmen, die KI-APIs wirtschaftlich einsetzen wollen.

---

## 2. Datenquellen

### 2.1 Preis-Crawler (automatisch)
- Täglicher HTTP-Crawler gegen öffentliche Pricing-Seiten der Anbieter
- Parsing via CSS-Selektoren / JSON-API (z. B. OpenAI Pricing JSON)
- Fallback: Selenium-Headless für JS-gerenderte Seiten
- Scheduler: APScheduler (bereits im Projekt vorhanden) – Job `crawl_prices` täglich 02:00 UTC

### 2.2 Manuelle Pflege (Admin)
- Geschützte `POST /admin/providers` und `PATCH /admin/providers/{id}` Endpunkte
- CSV-Import für Bulk-Updates
- Audit-Log aller Preisänderungen in `price_history`

### 2.3 Partner-APIs
- Anbieter können eigene Preis-Feeds (JSON/Webhook) registrieren
- Verifizierung via HMAC-Signatur
- Priorisiert gegenüber Crawler-Daten (Quelle = `partner`)

---

## 3. Technische Umsetzung

### 3.1 Neue API-Endpunkte

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET` | `/compare` | Anbietervergleich mit Filter/Sort |
| `GET` | `/compare/{provider_id}` | Detail-Ansicht eines Anbieters |
| `GET` | `/compare/history/{provider_id}` | Preisverlauf (30/90/365 Tage) |
| `POST` | `/admin/providers` | Anbieter anlegen (Auth required) |
| `PATCH` | `/admin/providers/{id}` | Anbieter aktualisieren |
| `POST` | `/partner/price-feed` | Partner-Preis-Feed empfangen |

#### `/compare` Query-Parameter
```
GET /compare?model=gpt-4o&sort=price_input_asc&min_context=128000&free_tier=true
```

| Parameter | Typ | Beschreibung |
|-----------|-----|--------------|
| `model` | string | Filter auf Modellname (fuzzy) |
| `sort` | enum | `price_input_asc`, `latency_asc`, `uptime_desc` |
| `min_context` | int | Mindest-Kontextfenster in Token |
| `free_tier` | bool | Nur Anbieter mit Free-Tier |
| `modality` | string | `text`, `vision`, `audio` |

#### Beispiel-Response
```json
{
  "updated_at": "2026-03-06T02:00:00Z",
  "results": [
    {
      "provider": "DeepSeek",
      "model": "deepseek-chat",
      "price_input_per_1m": 0.14,
      "price_output_per_1m": 0.28,
      "context_window": 64000,
      "uptime_30d": 99.7,
      "latency_p50_ms": 420,
      "free_tier": false,
      "source": "crawler",
      "last_updated": "2026-03-06T02:03:11Z"
    }
  ]
}
```

### 3.2 Neue Datenbanktabelle: `price_history`

```sql
CREATE TABLE price_history (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider_id     UUID NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
  model           TEXT NOT NULL,
  price_input     NUMERIC(12, 6) NOT NULL,  -- USD per 1M tokens
  price_output    NUMERIC(12, 6) NOT NULL,
  context_window  INTEGER,
  uptime_30d      NUMERIC(5, 2),
  latency_p50_ms  INTEGER,
  source          TEXT NOT NULL DEFAULT 'crawler',  -- 'crawler' | 'manual' | 'partner'
  recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_price_history_provider_model ON price_history(provider_id, model, recorded_at DESC);
```

Migration: `infra/migrations/004_create_price_history.sql`

### 3.3 Hintergrund-Jobs

```python
# backend/app/jobs/price_crawler.py

async def crawl_prices():
    """Täglich 02:00 UTC – holt aktuelle Preise aller Anbieter."""
    providers = CRAWLER_TARGETS  # dict: name → URL + parser
    for name, config in providers.items():
        price_data = await fetch_and_parse(config)
        await upsert_price_history(name, price_data, source="crawler")
    await notify_discord(f"✅ Preis-Crawl abgeschlossen: {len(providers)} Anbieter aktualisiert")
```

APScheduler-Eintrag in `main.py`:
```python
scheduler.add_job(crawl_prices, "cron", hour=2, minute=0)
```

### 3.4 Technologie-Stack (Delta zu MVP 1/2)

| Komponente | Lösung |
|------------|--------|
| Crawler | `httpx` + `beautifulsoup4` (bereits vorhanden) |
| Scheduler | APScheduler (bereits vorhanden) |
| DB | Supabase – neue Tabelle `price_history` |
| Cache | Redis (optional) – `/compare` Response 5 min TTL |
| Frontend | Erweiterung von `frontend/index.html` (Vergleichs-Tabelle) |

---

## 4. Geschäftsmodell

### 4.1 Provision (Affiliate)
- TokenBroker erhält **2–5 %** der vermittelten Token-Kosten als Provision
- Tracking via UTM-Parameter + Klick-Log (`provider_clicks`-Tabelle)
- Auszahlung monatlich, Mindestbetrag 50 USD

### 4.2 Premium-Listenplätze
- Anbieter zahlen für **hervorgehobene Platzierung** (Sponsored-Badge)
- Preis: 200–500 USD/Monat je nach Traffic
- Transparenz: Nutzer sehen deutlich „Gesponsert"-Label

### 4.3 Abonnements (B2B)
| Plan | Preis | Features |
|------|-------|---------|
| Free | 0 €/Monat | Vergleich, 7-Tage-History |
| Pro | 19 €/Monat | 1-Jahr-History, API-Zugang, Alerts |
| Enterprise | 199 €/Monat | White-Label, eigene Crawler-Targets, SLA |

### 4.4 Preis-Alerts (Upsell)
- Nutzer abonnieren Preisänderungs-Alerts per E-Mail/Discord/Webhook
- Feature für Pro+Enterprise

### 4.5 Umsatzprognose (konservativ)
- Monat 3: 5 Sponsored-Slots × 200 € = 1.000 €
- Monat 6: 50 Pro-Abos × 19 € + Affiliate = ~2.500 €
- Monat 12: 3 Enterprise + 200 Pro + Affiliate = ~10.000 €

---

## 5. Roadmap

### Phase 1 – Foundation (Woche 1–2)
- [ ] Migration `004_create_price_history.sql` einspielen
- [ ] `GET /compare` Basis-Endpunkt (statische Daten aus DB)
- [ ] Manuelle Admin-Endpunkte (`POST /admin/providers`)
- [ ] 5 Anbieter manuell erfassen: OpenAI, Anthropic, NVIDIA, DeepSeek, Mistral

### Phase 2 – Crawler (Woche 3–4)
- [ ] `jobs/price_crawler.py` implementieren
- [ ] Parser für OpenAI, DeepSeek, Mistral Pricing-Seiten
- [ ] APScheduler-Job registrieren
- [ ] Discord-Alert bei Preisänderung > 10 %
- [ ] 20+ Tests für Crawler + Endpunkte

### Phase 3 – Frontend (Woche 5–6)
- [ ] Vergleichs-Tabelle in `frontend/index.html`
- [ ] Filter-UI (Modell, Preis, Latenz)
- [ ] Preisverlauf-Chart (Chart.js)
- [ ] Mobile-responsiv

### Phase 4 – Monetarisierung (Woche 7–8)
- [ ] Affiliate-Tracking implementieren
- [ ] Stripe-Abo-Integration (Basis aus MVP 2)
- [ ] Premium-Listing-Verwaltung
- [ ] Preis-Alert-System (E-Mail via SendGrid)

### Phase 5 – Launch (Woche 9–10)
- [ ] Beta-Launch mit 10 Pilotnutzern
- [ ] SEO-Landingpage
- [ ] Product Hunt Launch
- [ ] Erste Partner-Gespräche mit Anbietern

---

## 6. UI-Konzept (Skizze)

```
╔══════════════════════════════════════════════════════════════════╗
║  TokenBroker Compare  🔍 [Modell suchen...]  [Filter ▼]        ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  Filter: [Alle Modelle ▼]  [Preis ↑↓]  [✓ Free-Tier]          ║
║                                                                  ║
╠══════╦══════════╦════════════╦═══════════╦══════════╦══════════╣
║ Rang ║ Anbieter ║ Modell     ║ Input/1M  ║ Out/1M   ║ Uptime   ║
╠══════╬══════════╬════════════╬═══════════╬══════════╬══════════╣
║  1   ║ DeepSeek ║ deepseek-… ║  $0.14    ║  $0.28   ║ 99.7%   ║
║  2   ║ Mistral  ║ mistral-s… ║  $0.20    ║  $0.60   ║ 99.5%   ║
║  3 ⭐║ NVIDIA   ║ llama-3.1… ║  $0.00 🆓 ║  $0.00   ║ 98.9%   ║
║      ║          ║  [Gesponsert]                               ║
║  4   ║ OpenAI   ║ gpt-4o-mi… ║  $0.15    ║  $0.60   ║ 99.9%   ║
║  5   ║ Anthropic║ claude-h…  ║  $0.80    ║  $4.00   ║ 99.8%   ║
╚══════╩══════════╩════════════╩═══════════╩══════════╩══════════╝

  [Anbieter vergleichen ✓ DeepSeek ✓ OpenAI]  →  [Vergleich starten]

──────────────────────────────────────────────────────────────────
  📈 Preisverlauf – DeepSeek deepseek-chat (letzte 30 Tage)

  $0.30 ┤                     ╭──╮
  $0.20 ┤          ╭──────────╯  ╰──── $0.14 (aktuell)
  $0.10 ┤
        └──────────────────────────────────────────────
          01.Feb    10.Feb    20.Feb    01.Mär    06.Mär

──────────────────────────────────────────────────────────────────
  🔔 Preis-Alert einrichten:  [E-Mail eingeben...]  [Alert setzen]
  📋 API-Zugang: GET https://yondem-production.up.railway.app/compare
╚══════════════════════════════════════════════════════════════════╝
```

### Mobile-Ansicht (vereinfacht)
```
┌─────────────────────────┐
│ TokenBroker Compare     │
│ 🔍 [Suchen...]          │
├─────────────────────────┤
│ 1. DeepSeek             │
│    deepseek-chat        │
│    $0.14 / $0.28 per 1M │
│    Uptime: 99.7%        │
│    [Details →]          │
├─────────────────────────┤
│ 2. Mistral              │
│    mistral-small        │
│    $0.20 / $0.60 per 1M │
│    [Details →]          │
└─────────────────────────┘
```

---

## 7. Offene Fragen / Risiken

| Risiko | Mitigation |
|--------|-----------|
| Anbieter blockiert Crawler | User-Agent rotation, Robots.txt respektieren, Partner-Feed bevorzugen |
| Preisdaten veraltet | Timestamp + "Stand: vor X Stunden" im UI |
| Rechtliche Fragen (Preisvergleich) | Disclaimer: Preise ohne Gewähr, Link zur offiziellen Quelle |
| DSGVO (Alert-E-Mails) | Double-Opt-In, Datenschutzerklärung |
