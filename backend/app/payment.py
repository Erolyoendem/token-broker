from __future__ import annotations
import os
import stripe
from app.db import get_client

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")


def get_publishable_key() -> str:
    return os.getenv("STRIPE_PUBLISHABLE_KEY", "")


def create_payment_intent(
    group_buy_id: int,
    user_id: str,
    tokens: int,
) -> dict:
    """
    1. Fetch price_per_token from group_buys.
    2. Create Stripe PaymentIntent.
    3. Persist to payment_intents table.
    Returns {'client_secret': ..., 'amount': ..., 'currency': 'eur'}.
    """
    client = get_client()

    # Fetch group buy for price
    gb = (
        client.table("group_buys")
        .select("price_per_token, provider")
        .eq("id", group_buy_id)
        .single()
        .execute()
        .data
    )
    if not gb:
        raise ValueError(f"Group buy {group_buy_id} not found")

    price_per_token = float(gb["price_per_token"])
    amount_eur = tokens * price_per_token
    amount_cents = max(1, int(round(amount_eur * 100)))  # Stripe needs cents, min 1

    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency="eur",
        metadata={
            "group_buy_id": group_buy_id,
            "user_id": user_id,
            "tokens": tokens,
        },
    )

    # Persist
    client.table("payment_intents").insert({
        "stripe_payment_intent_id": intent.id,
        "group_buy_id": group_buy_id,
        "user_id": user_id,
        "amount": amount_cents,
        "status": intent.status,
    }).execute()

    return {
        "client_secret": intent.client_secret,
        "amount": amount_cents,
        "currency": "eur",
        "payment_intent_id": intent.id,
    }


def handle_webhook(payload: bytes, sig_header: str) -> dict:
    """Validate and process Stripe webhook event."""
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except stripe.error.SignatureVerificationError:
        raise ValueError("Invalid webhook signature")

    client = get_client()

    if event["type"] == "payment_intent.succeeded":
        pi_id = event["data"]["object"]["id"]
        client.table("payment_intents").update({"status": "succeeded"}).eq(
            "stripe_payment_intent_id", pi_id
        ).execute()
        # Mark participant as paid
        pi_row = (
            client.table("payment_intents")
            .select("group_buy_id, user_id")
            .eq("stripe_payment_intent_id", pi_id)
            .single()
            .execute()
            .data
        )
        if pi_row:
            client.table("group_buy_participants").update({"paid": True}).eq(
                "group_buy_id", pi_row["group_buy_id"]
            ).eq("user_id", pi_row["user_id"]).execute()

    return {"received": True, "type": event["type"]}
