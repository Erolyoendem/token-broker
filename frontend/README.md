# TokenBroker – Frontend

Statisches Single-Page-Frontend fuer die Group-Buy-Funktion von TokenBroker.
Kein Build-Schritt – direkt als statisches HTML nutzbar.

## Starten

```bash
# Option A: Direkt im Browser oeffnen
open frontend/index.html

# Option B: Lokaler Dev-Server (empfohlen fuer Stripe)
npx serve frontend
# oder
python3 -m http.server 3000 --directory frontend
```

> Stripe.js erfordert HTTPS oder localhost. Bei `file://`-URLs funktioniert
> die Zahlungsintegration moeglicherweise nicht vollstaendig.

Live-Version: https://yondem-production.up.railway.app *(Backend-URL, kein eigenstaendiges Hosting)*

---

## Features

| Feature | Endpunkt | Status |
|---|---|---|
| Kampagnen laden | `GET /group-buys` | fertig |
| Fortschrittsbalken | – | fertig |
| Teilnehmer-Detailansicht | `GET /group-buys/{id}` | fertig |
| Kampagne beitreten | `POST /group-buys/{id}/join` | fertig |
| Stripe PaymentElement | `POST /payment/create-intent` | fertig |

---

## Nutzung

### 1. Verbindung

- **API-Key**: Dein `X-TokenBroker-Key` (Format: `tb_…`)
- **Backend-URL**: Standard ist `https://yondem-production.up.railway.app`
- Klick auf **"Kampagnen laden"**

### 2. Kampagne auswaehlen

- Klick auf eine Kampagnenkarte zeigt die Detailansicht
- Fortschrittsbalken: aktueller vs. Ziel-Token-Stand
- Teilnehmerliste mit Beitrittsstatus (Bezahlt / Ausstehend)

### 3. Beitreten

- Token-Menge eingeben (Mindest: 1)
- Klick auf **"Beitreten"** sendet `POST /group-buys/{id}/join`
- Fortschrittsbalken aktualisiert sich automatisch

### 4. Stripe-Zahlung (Test)

Nach dem Beitreten erscheint automatisch das Stripe PaymentElement.

```
Test-Karte:   4242 4242 4242 4242
Ablaufdatum:  beliebig in der Zukunft (z.B. 12/29)
CVC:          beliebig (z.B. 123)
```

Ablauf intern:
1. Frontend holt `publishable_key` von `GET /payment/config`
2. Backend erstellt Payment Intent – Betrag serverseitig berechnet
3. Stripe.js wird dynamisch geladen, `PaymentElement` wird gemountet
4. Klick auf **"Jetzt bezahlen"** → `stripe.confirmPayment()`

---

## API-Endpunkte (Backend)

| Endpunkt | Methode | Beschreibung |
|---|---|---|
| `/group-buys` | GET | Liste aktiver Kampagnen |
| `/group-buys/{id}` | GET | Detail + Teilnehmerliste |
| `/group-buys/{id}/join` | POST | Kampagne beitreten |
| `/payment/config` | GET | Stripe Publishable Key |
| `/payment/create-intent` | POST | Payment Intent erstellen |

Alle Endpunkte (ausser `/payment/config`) erfordern den Header:
```
X-TokenBroker-Key: tb_...
```

---

## Umgebungsvariablen (Backend, Railway)

| Variable | Beschreibung |
|---|---|
| `STRIPE_SECRET_KEY` | Stripe Secret Key (`sk_test_…` fuer Tests) |
| `STRIPE_PUBLISHABLE_KEY` | Fuer `GET /payment/config` |
| `STRIPE_WEBHOOK_SECRET` | Fuer Webhook-Signaturvalidierung |
| `DEEPSEEK_API_KEY` | DeepSeek-Fallback-Provider |
| `NVIDIA_API_KEY` | Primaerer Provider (free-tier) |
| `DISCORD_WEBHOOK_URL` | Benachrichtigungen bei Chat-Calls |
