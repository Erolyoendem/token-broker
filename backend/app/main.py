from fastapi import FastAPI, HTTPException, Depends, Header
from contextlib import asynccontextmanager
from typing import Optional
from pydantic import BaseModel
from dotenv import load_dotenv
import os
from apscheduler.schedulers.background import BackgroundScheduler

from app.router import get_cheapest_provider, get_provider_by_name, call_with_fallback
from app.db_providers import get_active_providers_from_db
from app.usage import log_usage, get_total_usage
from app.discord import notify
from app.auth import require_api_key, verify_user_api_key
from app.crowdfunding import create_group_buy, join_group_buy, check_and_trigger
from app.trigger import process_completed_group_buys
from app.db import get_client
from app.payment import get_publishable_key, create_payment_intent, handle_webhook

load_dotenv()
TOKEN_LIMIT_DEFAULT = int(os.getenv("TOKEN_LIMIT_DEFAULT", "1000000"))

_scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _scheduler.add_job(process_completed_group_buys, "interval", minutes=5, id="trigger_job")
    _scheduler.start()
    yield
    _scheduler.shutdown()


app = FastAPI(title="TokenBroker API", version="0.1.0", lifespan=lifespan)


class ChatRequest(BaseModel):
    messages: list[dict]
    provider: Optional[str] = None
    model: Optional[str] = None


class GroupBuyRequest(BaseModel):
    name: str
    target_tokens: int
    price_per_token: float
    provider: str
    expires_at: Optional[str] = None


class JoinRequest(BaseModel):
    tokens: int


class PaymentIntentRequest(BaseModel):
    group_buy_id: int
    tokens: int


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


@app.post("/group-buys")
def create_group_buy_endpoint(
    request: GroupBuyRequest,
    user_id: str = Depends(require_api_key),
):
    row = create_group_buy(
        name=request.name,
        target_tokens=request.target_tokens,
        price_per_token=request.price_per_token,
        provider=request.provider,
        expires_at=request.expires_at,
    )
    return {"id": row["id"], "status": row["status"], "name": row["name"]}


@app.post("/group-buys/{group_buy_id}/join")
def join_group_buy_endpoint(
    group_buy_id: int,
    request: JoinRequest,
    user_id: str = Depends(require_api_key),
):
    updated = join_group_buy(group_buy_id, user_id, request.tokens)
    result = check_and_trigger(group_buy_id)
    return {
        "group_buy_id": group_buy_id,
        "current_tokens": updated["current_tokens"],
        "status": result["status"],
    }


@app.get("/group-buys")
def list_group_buys(user_id: str = Depends(require_api_key)):
    client = get_client()
    rows = (
        client.table("group_buys")
        .select("*")
        .in_("status", ["pending", "active"])
        .execute()
        .data
    )
    return rows


@app.get("/group-buys/{group_buy_id}")
def get_group_buy(group_buy_id: int, user_id: str = Depends(require_api_key)):
    client = get_client()
    row = client.table("group_buys").select("*").eq("id", group_buy_id).single().execute().data
    if not row:
        raise HTTPException(status_code=404, detail="Group buy not found")
    participants = (
        client.table("group_buy_participants")
        .select("user_id, tokens_ordered, paid, created_at")
        .eq("group_buy_id", group_buy_id)
        .execute()
        .data
    )
    return {**row, "participants": participants}


@app.post("/group-buys/{group_buy_id}/trigger")
def trigger_group_buy(group_buy_id: int, user_id: str = Depends(require_api_key)):
    """Manually trigger purchase check for a single group buy (admin/system use)."""
    client = get_client()
    row = client.table("group_buys").select("*").eq("id", group_buy_id).single().execute().data
    if not row:
        raise HTTPException(status_code=404, detail="Group buy not found")
    if row["status"] != "pending":
        return {"group_buy_id": group_buy_id, "status": row["status"], "triggered": False}
    if (row.get("current_tokens") or 0) < row["target_tokens"]:
        return {"group_buy_id": group_buy_id, "status": "pending", "triggered": False,
                "reason": "Target not reached yet"}
    triggered = process_completed_group_buys()
    activated = next((r for r in triggered if r["id"] == group_buy_id), None)
    if activated:
        return {"group_buy_id": group_buy_id, "status": "active", "triggered": True}
    return {"group_buy_id": group_buy_id, "status": row["status"], "triggered": False}


@app.get("/payment/config")
def payment_config():
    """Public endpoint – returns Stripe publishable key for frontend."""
    return {"publishable_key": get_publishable_key()}


@app.post("/payment/create-intent")
def payment_create_intent(
    request: PaymentIntentRequest,
    user_id: str = Depends(require_api_key),
):
    # Register participant (paid=false) then create Stripe intent
    join_group_buy(request.group_buy_id, user_id, request.tokens)
    try:
        result = create_payment_intent(request.group_buy_id, user_id, request.tokens)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Stripe error: {e}")
    return result


from fastapi import Request

@app.post("/payment/webhook/stripe")
async def stripe_webhook(req: Request):
    payload = await req.body()
    sig = req.headers.get("stripe-signature", "")
    try:
        result = handle_webhook(payload, sig)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@app.post("/v1/chat/completions")
async def openai_compat(
    request: ChatRequest,
    authorization: Optional[str] = Header(None),
):
    """OpenAI-compatible endpoint for tools like Goose. Bearer token = TokenBroker key."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    user_id = verify_user_api_key(token) if token else None
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    api_keys = {
        "nvidia": os.getenv("NVIDIA_API_KEY", ""),
        "deepseek": os.getenv("DEEPSEEK_API_KEY", ""),
    }
    try:
        result, provider = await call_with_fallback(request.messages, api_keys)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    tokens_used = result.get("usage", {}).get("total_tokens", 0)
    if tokens_used:
        log_usage(user_id=user_id, tokens_used=tokens_used, provider=provider.name)

    # Return raw OpenAI-format response (already in that format from providers)
    return result


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
