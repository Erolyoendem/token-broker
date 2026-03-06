from fastapi import Header, HTTPException
from app.db import get_client


def require_api_key(x_api_key: str = Header(..., description="TokenBroker API key")) -> str:
    """Validate x-api-key against Supabase api_keys table. Returns user_id."""
    client = get_client()
    result = client.table("api_keys").select("user_id").eq("key", x_api_key).single().execute()
    if not result.data:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return str(result.data["user_id"])
