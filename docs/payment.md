# Zahlungsintegration – TokenBroker MVP 2

## Ziel

Crowdfunding-Teilnehmer (`group_buy_participants`) sollen ihren Anteil bezahlen können.
Zahlungsanbieter der Wahl: **Stripe** (einfachste API, gute Testumgebung, EU-konform).

---

## Stripe – Überblick

| Merkmal            | Details                                      |
|--------------------|----------------------------------------------|
| API-Typ            | REST + Webhooks                              |
| SDKs               | Python (`stripe`), JS, u.v.m.                |
| Testmodus          | Vollständig ohne echte Karte testbar         |
| Preismodell        | 1,5 % + 0,25 € (EU-Karte, Standardgebühr)   |

---

## Integrationsschritte

### 1. Stripe-Account & API-Keys

1. Account anlegen unter https://dashboard.stripe.com/register
2. Im Dashboard → **Developers → API keys**
3. Zwei Keys notieren:
   - `STRIPE_SECRET_KEY` (nur serverseitig, **nie ins Repo**)
   - `STRIPE_PUBLISHABLE_KEY` (für Frontend sicher verwendbar)
4. Keys in `.env` eintragen (`.env` ist in `.gitignore`):
   ```
   STRIPE_SECRET_KEY=sk_test_...
   STRIPE_PUBLISHABLE_KEY=pk_test_...
   ```

### 2. Python-Paket installieren

```bash
pip install stripe
echo "stripe>=8.0.0" >> backend/requirements.txt
```

### 3. Backend-Endpunkte

#### 3a. Payment Intent erstellen

**Datei:** `backend/app/payment.py`

```python
import os
import stripe
from fastapi import APIRouter, HTTPException, Header, Request
from app.auth import verify_user_api_key
from app.db import get_client

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
router = APIRouter(prefix="/payment", tags=["payment"])

@router.post("/create-intent")
def create_payment_intent(
    group_buy_id: int,
    x_tokenbroker_key: str = Header(...),
):
    user_id = verify_user_api_key(x_tokenbroker_key)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid API key")

    client = get_client()
    row = (
        client.table("group_buy_participants")
        .select("tokens_ordered")
        .eq("group_buy_id", group_buy_id)
        .eq("user_id", user_id)
        .single()
        .execute()
        .data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Participation not found")

    gb = (
        client.table("group_buys")
        .select("price_per_token")
        .eq("id", group_buy_id)
        .single()
        .execute()
        .data
    )
    amount_cents = int(row["tokens_ordered"] * gb["price_per_token"] * 100)

    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency="eur",
        metadata={"user_id": user_id, "group_buy_id": group_buy_id},
    )
    return {"client_secret": intent.client_secret}
```

#### 3b. Webhook für Zahlungsbestätigung

```python
@router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, secret)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "payment_intent.succeeded":
        meta = event["data"]["object"]["metadata"]
        client = get_client()
        client.table("group_buy_participants").update({"paid": True}) \
            .eq("group_buy_id", meta["group_buy_id"]) \
            .eq("user_id", meta["user_id"]) \
            .execute()

    return {"received": True}
```

#### 3c. Endpunkt für den Publishable Key (Frontend)

```python
@router.get("/config")
def payment_config():
    return {"publishable_key": os.getenv("STRIPE_PUBLISHABLE_KEY", "")}
```

#### 3d. Router in `main.py` einbinden

```python
from app.payment import router as payment_router
app.include_router(payment_router)
```

### 4. Datenbank-Migration

```sql
-- infra/migrations/003_add_payment_fields.sql
ALTER TABLE group_buy_participants
  ADD COLUMN IF NOT EXISTS stripe_payment_intent_id TEXT,
  ADD COLUMN IF NOT EXISTS paid_at TIMESTAMP;
```

### 5. Webhook-URL registrieren

```bash
# Lokal testen mit Stripe CLI:
stripe listen --forward-to localhost:8000/payment/webhook

# In Produktion (Railway):
# Dashboard → Developers → Webhooks → Add endpoint
# URL: https://yondem-production.up.railway.app/payment/webhook
# Events: payment_intent.succeeded
```

### 6. Frontend

Siehe `frontend/index.html` – minimaler Prototyp mit Stripe.js.
Der `STRIPE_PUBLISHABLE_KEY` wird vom Backend via `/payment/config` ausgeliefert.

---

## Sicherheitshinweise

- `STRIPE_SECRET_KEY` **niemals** in Git einchecken
- Webhook-Signatur **immer** validieren (gegen Replay-Attacks)
- `amount` serverseitig berechnen, nie vom Client entgegennehmen
- HTTPS in Produktion Pflicht (Railway stellt das automatisch bereit)

---

## Test-Kreditkarten (Stripe Testmodus)

| Karte                   | Ergebnis                    |
|-------------------------|-----------------------------|
| 4242 4242 4242 4242      | Zahlung erfolgreich         |
| 4000 0000 0000 0002      | Karte abgelehnt             |
| 4000 0025 0000 3155      | 3D-Secure erforderlich      |

---

## Nächste Schritte

- [ ] `backend/app/payment.py` implementieren
- [ ] Migration `003_add_payment_fields.sql` einspielen
- [ ] Stripe-Webhook in Railway-Dashboard konfigurieren
- [ ] Tests für `/payment/create-intent` und `/payment/webhook` schreiben
- [ ] Frontend-Prototyp mit echtem `pk_test_...` verbinden
