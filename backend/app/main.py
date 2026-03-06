from fastapi import FastAPI, HTTPException, Depends, Header
from typing import Optional
from pydantic import BaseModel
from dotenv import load_dotenv
import os

from app.router import get_cheapest_provider, get_provider_by_name, call_with_fallback
from app.db_providers import get_active_providers_from_db
from app.usage import log_usage, get_total_usage
from app.discord import notify
from app.auth import require_api_key, verify_user_api_key

load_dotenv()
TOKEN_LIMIT_DEFAULT = int(os.getenv("TOKEN_LIMIT_DEFAULT", "1000000"))

app = FastAPI(title="TokenBroker API", version="0.1.0")


class ChatRequest(BaseModel):
    messages: list[dict]
    provider: Optional[str] = None   # optional: force a specific provider
    model: Optional[str] = None


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "TokenBroker"}


@app.get("/providers")
def list_providers():
    providers = get_active_providers_from_db()
    return [
        {
            "name": p.name,
            "model": p.model,
            "active": p.active,
            "input_price_per_million": p.input_price_per_million,
            "output_price_per_million": p.output_price_per_million,
        }
        for p in providers
    ]


@app.get("/usage/{user_id}")
def usage(user_id: str, authenticated_user_id: str = Depends(require_api_key)):
    if user_id != authenticated_user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    total = get_total_usage(user_id)
    return {"user_id": user_id, "tokens_used": total, "limit": TOKEN_LIMIT_DEFAULT}


@app.post("/chat")
async def chat(
    request: ChatRequest,
    x_tokenbroker_key: str = Header(..., description="TokenBroker user API key"),
):
    user_id = verify_user_api_key(x_tokenbroker_key)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    current_usage = get_total_usage(user_id)
    if current_usage >= TOKEN_LIMIT_DEFAULT:
        raise HTTPException(status_code=429, detail=f"Token limit reached ({TOKEN_LIMIT_DEFAULT} tokens)")

    # Provider keys come exclusively from environment variables
    api_keys = {
        "nvidia": os.getenv("NVIDIA_API_KEY", ""),
        "deepseek": os.getenv("DEEPSEEK_API_KEY", ""),
    }

    if request.provider:
        try:
            forced = get_provider_by_name(request.provider)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        providers_pool = [forced]
    else:
        providers_pool = None  # all active, cheapest-first

    try:
        result, provider = await call_with_fallback(
            request.messages, api_keys, providers=providers_pool
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Verbrauch loggen
    tokens_used = result.get("usage", {}).get("total_tokens", 0)
    if tokens_used:
        log_usage(user_id=user_id, tokens_used=tokens_used, provider=provider.name)
        await notify(
            f"📨 **TokenBroker** | user: `{user_id}` | provider: `{provider.name}` | tokens: `{tokens_used}`"
        )

    return {
        "provider": provider.name,
        "model": provider.model,
        "tokens_used": tokens_used,
        "response": result,
    }
