from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from typing import Optional
from pydantic import BaseModel
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler

from app.router import get_cheapest_provider, get_provider_by_name, call_with_fallback, get_best_model, VALID_PREFERENCES
from app.db_providers import get_active_providers_from_db
from app.usage import log_usage, get_total_usage
from app.discord import notify
from app.auth import require_api_key, verify_user_api_key
from app.crowdfunding import create_group_buy, join_group_buy, check_and_trigger
from app.trigger import process_completed_group_buys
from app.db import get_client
from app.payment import get_publishable_key, create_payment_intent, handle_webhook
from app import metrics
from llm_benchmark.api import router as benchmark_router
from app.swarm import router as swarm_router
from tenant import router as tenant_router
from agent_swarm import Orchestrator, SwarmMemory
from market_intelligence import CompetitorTracker, TrendAnalyzer, OpportunityDetector, ReportGenerator
from agent_evolution import RLAgent, train_from_db, train_combined
from training_data.dataset import DatasetManager
from evolution.metrics_collector import MetricsCollector
from evolution.experiment_manager import ExperimentManager
from evolution.auto_optimizer import AutoOptimizer
from evolution.version_control import VersionControl

_evo_collector   = MetricsCollector()
_evo_experiments = ExperimentManager()
_evo_optimizer   = AutoOptimizer(_evo_collector)
_evo_vc          = VersionControl()

load_dotenv()
TOKEN_LIMIT_DEFAULT = int(os.getenv("TOKEN_LIMIT_DEFAULT", "1000000"))
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

_scheduler = BackgroundScheduler()


def _weekly_prompt_optimization() -> None:
    """APScheduler job: run one PromptOptimizer cycle every week."""
    from agent_swarm.memory import SwarmMemory
    from agent_swarm.prompt_optimizer import PromptOptimizer
    from agent_swarm.generation_agent import PROMPT_VARIANTS
    import logging
    log = logging.getLogger("prompt_optimizer.scheduler")
    try:
        memory = SwarmMemory()
        optimizer = PromptOptimizer(memory)
        updated = optimizer.run_optimization_cycle(dict(PROMPT_VARIANTS))
        log.info("Weekly prompt optimization done. Variants: %s", list(updated.keys()))
    except Exception as exc:
        log.error("Weekly prompt optimization failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _scheduler.add_job(process_completed_group_buys, "interval", minutes=5, id="trigger_job")
    _scheduler.add_job(_weekly_prompt_optimization, "cron", day_of_week="sun", hour=3,
                       minute=0, id="weekly_prompt_opt", replace_existing=True)
    from scripts.run_benchmark import weekly_job as _benchmark_job
    _scheduler.add_job(_benchmark_job, "cron", day_of_week="mon", hour=2, minute=0,
                       id="weekly_benchmark", replace_existing=True)
    _scheduler.start()
    yield
    _scheduler.shutdown()


app = FastAPI(title="TokenBroker API", version="0.1.0", lifespan=lifespan)
app.include_router(tenant_router)
app.include_router(benchmark_router)
app.include_router(swarm_router)


@app.middleware("http")
async def track_requests(request: Request, call_next):
    response = await call_next(request)
    metrics.record_request(request.url.path, response.status_code)
    return response


def require_admin_key(x_admin_key: str = Header(..., description="Admin API key")) -> None:
    if not ADMIN_API_KEY or x_admin_key != ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")


class ChatRequest(BaseModel):
    messages: list[dict]
    provider: Optional[str] = None
    model: Optional[str] = None
    preference: Optional[str] = None   # accuracy | speed | cost | balanced
    task_type: Optional[str] = None    # math | code_gen | code_convert | factual | creative


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
    try:
        get_provider_by_name(request.provider)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
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

    if request.preference and request.preference not in VALID_PREFERENCES:
        raise HTTPException(status_code=400, detail=f"Invalid preference '{request.preference}'. Valid: {sorted(VALID_PREFERENCES)}")

    api_keys = {
        "nvidia": os.getenv("NVIDIA_API_KEY", ""),
        "deepseek": os.getenv("DEEPSEEK_API_KEY", ""),
    }

    # Dynamic routing when preference or task_type is set (and no explicit provider)
    if not request.provider and (request.preference or request.task_type):
        best = get_best_model(
            task_type=request.task_type,
            preference=request.preference or "balanced",
        )
        providers_pool = [best] if best else None
    else:
        providers_pool = None

    try:
        result, provider = await call_with_fallback(request.messages, api_keys, providers=providers_pool)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    tokens_used = result.get("usage", {}).get("total_tokens", 0)
    if tokens_used:
        log_usage(user_id=user_id, tokens_used=tokens_used, provider=provider.name)

    # Return raw OpenAI-format response (already in that format from providers)
    return result


@app.get("/stats/token-usage")
def stats_token_usage(_: None = Depends(require_admin_key)):
    """Token usage per provider for today (UTC)."""
    client = get_client()
    since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    try:
        rows = (
            client.table("token_usage")
            .select("provider, tokens_used, timestamp")
            .gte("timestamp", since)
            .execute()
            .data
        ) or []
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DB error: {exc}")

    by_provider: dict[str, int] = {}
    for row in rows:
        p = row["provider"]
        by_provider[p] = by_provider.get(p, 0) + row["tokens_used"]

    return {
        "date": since[:10],
        "total_tokens": sum(by_provider.values()),
        "by_provider": [{"provider": p, "tokens": t} for p, t in sorted(by_provider.items())],
    }


@app.get("/stats/group-buys")
def stats_group_buys(_: None = Depends(require_admin_key)):
    """Count of group buys by status."""
    client = get_client()
    try:
        rows = client.table("group_buys").select("status").execute().data or []
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DB error: {exc}")

    counts: dict[str, int] = {}
    for row in rows:
        s = row["status"]
        counts[s] = counts.get(s, 0) + 1

    return {
        "total": len(rows),
        "by_status": [{"status": s, "count": c} for s, c in sorted(counts.items())],
    }


@app.get("/stats/errors")
def stats_errors(_: None = Depends(require_admin_key)):
    """Error rates per endpoint (in-memory, resets on restart)."""
    return {"endpoints": metrics.get_error_rates()}


@app.get("/stats/agents")
def stats_agents(_: None = Depends(require_admin_key)):
    """Aggregated agent/swarm performance metrics from SwarmMemory."""
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent / "infra"))
        from agent_monitor import collect_agent_metrics
        return collect_agent_metrics()
    except Exception as exc:
        return {**_swarm_memory.aggregate_stats(), "source": "swarm_memory_fallback", "error": str(exc)}


# ── Evolution API ─────────────────────────────────────────────────────────────

class FreezeRequest(BaseModel):
    winner: str


@app.get("/evolution/stats")
def evolution_stats(_: None = Depends(require_admin_key)):
    """Aggregated provider stats for the last 24 h (from evolution DB)."""
    return {"providers": _evo_collector.get_stats(last_hours=24)}


@app.get("/evolution/trend")
def evolution_trend(_: None = Depends(require_admin_key)):
    """Daily success-rate trend for the last 7 days."""
    return {"days": _evo_collector.get_daily_trend(days=7)}


@app.get("/evolution/provider-scores")
def evolution_provider_scores(_: None = Depends(require_admin_key)):
    """Thompson-Sampling scores per provider."""
    candidates = ["nvidia", "deepseek"]
    return {"providers": _evo_optimizer.provider_scores(candidates)}


@app.post("/evolution/optimize")
def evolution_optimize(_: None = Depends(require_admin_key)):
    """Manually trigger one prompt-optimization cycle (admin only)."""
    from agent_swarm.memory import SwarmMemory
    from agent_swarm.prompt_optimizer import PromptOptimizer
    from agent_swarm.generation_agent import PROMPT_VARIANTS

    memory = SwarmMemory()
    optimizer = PromptOptimizer(memory)
    updated = optimizer.run_optimization_cycle(dict(PROMPT_VARIANTS))
    added = [vid for vid in updated if vid not in PROMPT_VARIANTS]
    removed = [vid for vid in PROMPT_VARIANTS if vid not in updated]
    return {
        "status": "ok",
        "variants_total": len(updated),
        "added": added,
        "removed": removed,
        "variants": list(updated.keys()),
    }


@app.get("/evolution/alerts")
def evolution_alerts(_: None = Depends(require_admin_key)):
    """Threshold alerts (success rate < 60%, latency > 10s)."""
    return {"alerts": _evo_optimizer.check_thresholds()}


@app.get("/evolution/lessons")
def evolution_lessons(_: None = Depends(require_admin_key)):
    """Auto-generated best-practice lessons from last 7 days."""
    return {"lessons": _evo_optimizer.lessons_learned()}


@app.get("/evolution/experiments")
def evolution_experiments(_: None = Depends(require_admin_key)):
    """List all A/B experiments with summaries."""
    experiments = []
    for exp in _evo_experiments.list_experiments():
        try:
            summary = _evo_experiments.summary(exp["name"])
            experiments.append({**exp, "suggested_winner": summary.get("suggested_winner")})
        except Exception:
            experiments.append(exp)
    return {"experiments": experiments}


@app.post("/evolution/experiments/{name}/stop")
def evolution_experiment_stop(name: str, _: None = Depends(require_admin_key)):
    """Stop a running experiment."""
    try:
        _evo_experiments.stop(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Experiment '{name}' not found")
    return {"name": name, "status": "stopped"}


@app.post("/evolution/experiments/{name}/freeze")
def evolution_experiment_freeze(
    name: str,
    request: FreezeRequest,
    _: None = Depends(require_admin_key),
):
    """Freeze an experiment and declare a winner."""
    try:
        _evo_experiments.freeze(name, request.winner)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Experiment '{name}' not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"name": name, "status": "frozen", "winner": request.winner}


@app.get("/evolution/configs")
def evolution_configs(_: None = Depends(require_admin_key)):
    """List all saved evolution configs (Git-tagged)."""
    return {"configs": _evo_vc.list_configs()}


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

    if request.preference and request.preference not in VALID_PREFERENCES:
        raise HTTPException(status_code=400, detail=f"Invalid preference '{request.preference}'. Valid: {sorted(VALID_PREFERENCES)}")

    if request.provider:
        try:
            forced = get_provider_by_name(request.provider)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        providers_pool = [forced]
    elif request.preference or request.task_type:
        # Dynamic routing: pick best provider from benchmark data
        best = get_best_model(
            task_type=request.task_type,
            preference=request.preference or "balanced",
        )
        providers_pool = [best] if best else None
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
        "routing": request.preference or "default",
        "response": result,
    }


# ── User Preferences endpoints ────────────────────────────────────────────────

class PreferenceRequest(BaseModel):
    preference: str   # accuracy | speed | cost | balanced
    task_type: Optional[str] = None


@app.get("/preferences/{user_id}")
def get_preference(user_id: str, authenticated_user_id: str = Depends(require_api_key)):
    if user_id != authenticated_user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    client = get_client()
    try:
        row = client.table("user_preferences").select("*").eq("user_id", user_id).maybe_single().execute().data
    except Exception:
        row = None
    return {"user_id": user_id, "preference": (row or {}).get("preference", "balanced"),
            "task_type": (row or {}).get("task_type")}


@app.put("/preferences/{user_id}")
def set_preference(
    user_id: str,
    body: PreferenceRequest,
    authenticated_user_id: str = Depends(require_api_key),
):
    if user_id != authenticated_user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if body.preference not in VALID_PREFERENCES:
        raise HTTPException(status_code=400, detail=f"Invalid preference. Valid: {sorted(VALID_PREFERENCES)}")
    client = get_client()
    try:
        client.table("user_preferences").upsert({
            "user_id":    user_id,
            "preference": body.preference,
            "task_type":  body.task_type,
        }, on_conflict="user_id").execute()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"DB error: {e}")
    return {"user_id": user_id, "preference": body.preference, "task_type": body.task_type}


# ── Agent Swarm endpoints ──────────────────────────────────────────────────────

_swarm_memory = SwarmMemory()


class SwarmConvertRequest(BaseModel):
    filename: str
    ruby_code: str


@app.post("/swarm/train")
async def swarm_train(_: str = Depends(require_api_key)):
    """Run the self-optimising swarm over all Ruby files in swarm_input/."""
    ruby_dir = Path(__file__).parent.parent.parent / "swarm_input"
    if not ruby_dir.exists():
        raise HTTPException(status_code=404, detail=f"swarm_input/ not found at {ruby_dir}")
    orchestrator = Orchestrator(_swarm_memory, workers=5)
    summary = await orchestrator.train(ruby_dir)
    return summary


@app.get("/swarm/stats")
def swarm_stats(_: str = Depends(require_api_key)):
    """Return aggregate swarm performance metrics."""
    return _swarm_memory.aggregate_stats()


@app.post("/swarm/convert")
async def swarm_convert(req: SwarmConvertRequest, _: str = Depends(require_api_key)):
    """Convert a single Ruby snippet using the optimised swarm."""
    orchestrator = Orchestrator(_swarm_memory, workers=1)
    result = await orchestrator.convert_one(req.filename, req.ruby_code)
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "conversion failed"))
    return {
        "python_code": result["python_code"],
        "score": result["score"],
        "feedback": result["feedback"],
        "tokens": result["tokens"],
        "elapsed_s": result["elapsed_s"],
        "prompt_variant": result["prompt_variant"],
    }


# ── Market Intelligence endpoints ─────────────────────────────────────────────

@app.get("/market/analysis")
def market_analysis(_: None = Depends(require_admin_key)):
    """Full market scan: competitors, trends, opportunities."""
    tracker = CompetitorTracker()
    analyzer = TrendAnalyzer()
    detector = OpportunityDetector()
    reporter = ReportGenerator()

    competitors = tracker.scan_all()
    trends = analyzer.analyze(max_per_term=3)
    opportunities = detector.detect(competitor_scan=competitors)
    report_path = reporter.generate_weekly_report(competitors, trends, opportunities)
    strategy_path = reporter.generate_strategy_suggestions(opportunities)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "competitors": competitors,
        "trends": {
            "analyzed_at": trends["analyzed_at"],
            "total_papers": trends["total_papers"],
            "top_keywords": analyzer.top_keywords(trends),
        },
        "opportunities": opportunities,
        "report_saved": str(report_path),
        "strategy_saved": str(strategy_path),
    }


@app.get("/market/competitors")
def market_competitors(_: None = Depends(require_admin_key)):
    """GitHub stats for tracked competitors."""
    return CompetitorTracker().scan_all()


@app.get("/market/opportunities")
def market_opportunities(_: None = Depends(require_admin_key)):
    """Feature gap analysis vs competitors."""
    return OpportunityDetector().detect()


# ── Offline RL Training endpoint ──────────────────────────────────────────────

_rl_agent = RLAgent()


class OfflineTrainRequest(BaseModel):
    pair_id: str = "ruby->python"
    min_quality: float = 3.0
    n_steps: int = 300
    combined: bool = False


@app.post("/evolution/train-offline")
def evolution_train_offline(
    request: OfflineTrainRequest,
    _: None = Depends(require_admin_key),
):
    """Trigger offline behavior-cloning training from the training_pairs DB table.
    Set combined=true to blend in live SwarmMemory experiences as well.
    """
    if request.combined:
        result = train_combined(
            memory=_swarm_memory,
            rl_agent=_rl_agent,
            pair_id=request.pair_id,
            min_quality=request.min_quality,
            n_steps_online=request.n_steps,
            n_steps_offline=request.n_steps,
            verbose=False,
        )
    else:
        result = train_from_db(
            rl_agent=_rl_agent,
            pair_id=request.pair_id,
            min_quality=request.min_quality,
            n_steps=request.n_steps,
            verbose=False,
        )
    return result
