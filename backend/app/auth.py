from typing import Optional
from fastapi import Header, HTTPException
from app.db import get_client


def verify_user_api_key(api_key: str) -> Optional[str]:
    """Look up api_key in Supabase api_keys table. Returns user_id or None."""
    client = get_client()
    result = client.table("api_keys").select("user_id").eq("key", api_key).maybe_single().execute()
    if not result.data:
        return None
    return str(result.data["user_id"])


def require_api_key(x_api_key: str = Header(..., description="TokenBroker API key")) -> str:
    """FastAPI dependency: validates key, raises 401 on failure. Returns user_id."""
    user_id = verify_user_api_key(x_api_key)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return user_id
