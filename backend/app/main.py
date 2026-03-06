from fastapi import FastAPI, HTTPException, Header
from typing import Optional
from pydantic import BaseModel
from dotenv import load_dotenv
import os

from app.router import get_cheapest_provider, get_provider_by_name
from app.providers import ALL_PROVIDERS
from app.usage import log_usage, get_total_usage
from app.discord import notify

load_dotenv()
TOKEN_LIMIT_DEFAULT = int(os.getenv("TOKEN_LIMIT_DEFAULT", "1000000"))

app = FastAPI(title="TokenBroker API", version="0.1.0")


class ChatRequest(BaseModel):
    messages: list[dict]
    provider: Optional[str] = None   # optional: force a specific provider
    model: Optional[str] = None
    user_id: Optional[str] = None    # for usage tracking


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "TokenBroker"}


@app.get("/providers")
def list_providers():
    return [
        {
            "name": p.name,
            "model": p.model,
            "active": p.active,
            "input_price_per_million": p.input_price_per_million,
            "output_price_per_million": p.output_price_per_million,
        }
        for p in ALL_PROVIDERS
    ]


@app.get("/usage/{user_id}")
def usage(user_id: str):
    total = get_total_usage(user_id)
    return {"user_id": user_id, "tokens_used": total, "limit": TOKEN_LIMIT_DEFAULT}


@app.post("/chat")
async def chat(
    request: ChatRequest,
    x_api_key: str = Header(..., description="API key for the selected provider"),
):
    if request.provider:
        try:
            provider = get_provider_by_name(request.provider)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        provider = get_cheapest_provider()

    # Kontingent prüfen
    user_id = request.user_id or "anonymous"
    current_usage = get_total_usage(user_id)
    if current_usage >= TOKEN_LIMIT_DEFAULT:
        raise HTTPException(status_code=429, detail=f"Token limit reached ({TOKEN_LIMIT_DEFAULT} tokens)")

    try:
        result = await provider.chat(request.messages, api_key=x_api_key)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Provider error: {e}")

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
