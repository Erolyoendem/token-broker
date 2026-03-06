from __future__ import annotations
from typing import Optional
from app.db import get_client


def create_group_buy(
    name: str,
    target_tokens: int,
    price_per_token: float,
    provider: str,
    expires_at: Optional[str] = None,
) -> dict:
    """Create a new group buy campaign. Returns the created row."""
    client = get_client()
    payload = {
        "name": name,
        "target_tokens": target_tokens,
        "price_per_token": price_per_token,
        "provider": provider,
        "status": "pending",
    }
    if expires_at:
        payload["expires_at"] = expires_at
    result = client.table("group_buys").insert(payload).execute()
    return result.data[0]


def join_group_buy(group_buy_id: int, user_id: str, tokens: int) -> dict:
    """Add a participant and increment current_tokens. Returns updated group_buy."""
    client = get_client()

    # Insert participant
    client.table("group_buy_participants").insert({
        "group_buy_id": group_buy_id,
        "user_id": user_id,
        "tokens_ordered": tokens,
        "paid": False,
    }).execute()

    # Increment current_tokens via RPC-safe approach: fetch + update
    current = client.table("group_buys").select("current_tokens").eq("id", group_buy_id).single().execute()
    new_total = (current.data["current_tokens"] or 0) + tokens
    result = client.table("group_buys").update({"current_tokens": new_total}).eq("id", group_buy_id).execute()
    return result.data[0]


def check_and_trigger(group_buy_id: int) -> dict:
    """If target reached, set status to 'active'. Returns updated group_buy."""
    client = get_client()
    row = client.table("group_buys").select("*").eq("id", group_buy_id).single().execute().data

    if row["status"] != "pending":
        return row

    if row["current_tokens"] >= row["target_tokens"]:
        result = client.table("group_buys").update({"status": "active"}).eq("id", group_buy_id).execute()
        return result.data[0]

    return row
