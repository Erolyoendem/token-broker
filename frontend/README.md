# TokenBroker – Frontend

Statisches Single-Page-Frontend für die Group-Buy-Funktion von TokenBroker.

## Starten

Keine Build-Tools erforderlich. Datei direkt im Browser öffnen:

```bash
open frontend/index.html
# oder
python3 -m http.server 3000 --directory frontend
```

Live-Version: https://yondem-production.up.railway.app *(Backend-URL, kein eigenständiges Hosting)*

---

## Features

| Feature | Endpunkt | Status |
|---|---|---|
| Kampagnen laden | `GET /group-buys` | fertig |
| Fortschrittsbalken | – | fertig |
| Teilnehmer-Detailansicht | `GET /group-buys/{id}` | fertig |
| Kampagne beitreten | `POST /group-buys/{id}/join` | fertig |
| Stripe-Zahlung | `POST /payment/create-intent` | Frontend fertig, Backend ausstehend |

---

## Nutzung

### 1. Verbindung

- **API-Key**: Dein `X-TokenBroker-Key` (Format: `tb_…`)
- **Backend-URL**: Standard ist `https://yondem-production.up.railway.app`
- Klick auf **"Kampagnen laden"**

### 2. Kampagne auswählen

- Dropdown zeigt alle aktiven/pending Kampagnen mit aktuellem Füllstand
- Fortschrittsbalken: Token-Menge und Preis sichtbar
- Teilnehmer-Panel lädt automatisch mit Beitrittsstatus (bezahlt / ausstehend)
- **"Aktualisieren"** lädt Teilnehmer neu

### 3. Beitreten

- Token-Menge eingeben (Mindest: 1)
- Klick auf **"Beitreten"** sendet `POST /group-buys/{id}/join`
- Fortschrittsbalken und Teilnehmerliste aktualisieren sich automatisch

### 4. Stripe-Zahlung (Test)

Voraussetzung: Backend-Endpunkt `POST /payment/create-intent` muss implementiert sein.

```
Stripe Publishable Key:  pk_test_...  (Stripe Dashboard → Developers → API keys)
Test-Karte:              4242 4242 4242 4242
Ablaufdatum:             beliebig in der Zukunft (z.B. 12/29)
CVC:                     beliebig (z.B. 123)
```

Ablauf:
1. Stripe Publishable Key (Test) eingeben
2. **"Bezahlen vorbereiten"** – lädt Payment Intent vom Backend, mountet Stripe Elements
3. Kartendaten eingeben
4. **"Jetzt bezahlen"** – Stripe `confirmPayment()`

---

## Ausstehende Backend-Endpunkte

```
POST /payment/create-intent?group_buy_id={id}
     Headers: X-TokenBroker-Key
     Response: { "client_secret": "pi_...secret_..." }

GET  /payment/config
     Response: { "publishable_key": "pk_test_..." }
```

---

## Umgebungsvariablen (Backend, Railway)

| Variable | Beschreibung |
|---|---|
| `STRIPE_SECRET_KEY` | Stripe Secret Key (`sk_test_…` für Tests) |
| `STRIPE_PUBLISHABLE_KEY` | Optional, für `GET /payment/config` |
| `DEEPSEEK_API_KEY` | DeepSeek-Fallback-Provider |
| `NVIDIA_API_KEY` | Primärer Provider (free-tier) |
| `DISCORD_WEBHOOK_URL` | Benachrichtigungen bei Chat-Calls |
