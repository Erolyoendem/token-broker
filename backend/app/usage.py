from __future__ import annotations
import uuid
from app.db import get_client

# Stable UUID for anonymous users (deterministic)
ANONYMOUS_UUID = "00000000-0000-0000-0000-000000000001"


def _to_uuid(user_id: str) -> str:
    """Convert arbitrary string to a valid UUID, or return as-is if already valid."""
    try:
        uuid.UUID(user_id)
        return user_id
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, user_id))


def log_usage(user_id: str, tokens_used: int, provider: str) -> None:
    """Write a token usage record to Supabase."""
    client = get_client()
    client.table("token_usage").insert({
        "user_id": _to_uuid(user_id),
        "tokens_used": tokens_used,
        "provider": provider,
    }).execute()


def get_total_usage(user_id: str) -> int:
    """Return total tokens consumed by a user."""
    client = get_client()
    result = client.table("token_usage").select("tokens_used").eq("user_id", _to_uuid(user_id)).execute()
    return sum(row["tokens_used"] for row in result.data)
