from __future__ import annotations
from typing import Optional
import hashlib
import json
import logging
import time
import httpx
from app.providers import Provider, ALL_PROVIDERS
from app.db_providers import get_active_providers_from_db

log = logging.getLogger(__name__)

FALLBACK_STATUS_CODES = {429, 401, 403, 500, 502, 503, 504}

# Valid preference values and their benchmark sort keys
VALID_PREFERENCES = {"accuracy", "speed", "cost", "balanced"}

# Weights for composite ("balanced") score
_W_ACCURACY = 0.40
_W_SPEED    = 0.30
_W_COST     = 0.30

# Simple in-process response cache (identical prompts, TTL = 5 min)
_CACHE_TTL = 300
_response_cache: dict[str, tuple[dict, Provider, float]] = {}


def _cache_key(messages: list[dict]) -> str:
    return hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()


def _evict_expired() -> None:
    now = time.time()
    expired = [k for k, (_, _, ts) in _response_cache.items() if now - ts > _CACHE_TTL]
    for k in expired:
        del _response_cache[k]


def _load_providers(providers: Optional[list] = None) -> list[Provider]:
    if providers is not None:
        return providers
    try:
        return get_active_providers_from_db()
    except Exception:
        return ALL_PROVIDERS  # fallback to hardcoded if DB unavailable


def get_cheapest_provider(providers: Optional[list] = None) -> Provider:
    pool = _load_providers(providers)
    active = [p for p in pool if p.active]
    if not active:
        raise RuntimeError("No active providers available")
    return min(active, key=lambda p: p.cost_per_million())


def get_provider_by_name(name: str, providers: Optional[list] = None) -> Provider:
    pool = _load_providers(providers)
    for p in pool:
        if p.name == name:
            return p
    raise ValueError(f"Unknown provider: {name}")


def _sorted_providers(providers: Optional[list] = None) -> list[Provider]:
    return sorted(
        [p for p in _load_providers(providers) if p.active],
        key=lambda p: p.cost_per_million(),
    )


def get_best_model(
    task_type: Optional[str] = None,
    preference: str = "balanced",
    providers: Optional[list] = None,
) -> Optional[Provider]:
    """
    Select the best provider for a given task_type and user preference,
    using stored benchmark_results from Supabase.

    preference:
      - "accuracy" : highest pass-rate for the task category
      - "speed"    : lowest average latency
      - "cost"     : lowest cost per 1M tokens (from providers.py)
      - "balanced" : weighted composite (accuracy 40%, speed 30%, cost 30%)

    Returns None if no benchmark data is available (caller falls back to
    cheapest-first logic).
    """
    if preference not in VALID_PREFERENCES:
        preference = "balanced"

    try:
        from llm_benchmark.store import BenchmarkStore
        from app.providers import ALL_PROVIDERS as _ALL

        store = BenchmarkStore()
        rows = store.latest_results(category=task_type, limit=500)
        if not rows:
            return None

        # Aggregate per provider
        agg: dict[str, dict] = {}
        for row in rows:
            p = row["provider"]
            if p not in agg:
                agg[p] = {"passed": 0, "total": 0, "latency_sum": 0.0}
            agg[p]["total"] += 1
            if row["passed"]:
                agg[p]["passed"] += 1
            agg[p]["latency_sum"] += row.get("latency_s", 0.0)

        if not agg:
            return None

        # Build provider cost map
        cost_map = {p.name: p.cost_per_million() for p in (_load_providers(providers))}
        max_latency = max(
            v["latency_sum"] / v["total"] for v in agg.values() if v["total"]
        ) or 1.0
        max_cost = max(cost_map.get(p, 0.0) for p in agg) or 1.0

        def _score(pname: str, data: dict) -> float:
            n = data["total"]
            acc = data["passed"] / n if n else 0.0
            lat = data["latency_sum"] / n if n else 0.0
            cost = cost_map.get(pname, 0.0)

            if preference == "accuracy":
                return acc
            if preference == "speed":
                return 1.0 - lat / max_latency
            if preference == "cost":
                return 1.0 - cost / max_cost if max_cost > 0 else 1.0
            # balanced
            speed_s = 1.0 - lat / max_latency
            cost_s  = 1.0 - cost / max_cost if max_cost > 0 else 1.0
            return _W_ACCURACY * acc + _W_SPEED * speed_s + _W_COST * cost_s

        best_name = max(agg, key=lambda p: _score(p, agg[p]))
        log.info(
            "get_best_model: task=%s pref=%s → %s (score=%.3f)",
            task_type, preference, best_name, _score(best_name, agg[best_name])
        )
        try:
            return get_provider_by_name(best_name, providers)
        except ValueError:
            return None

    except Exception as exc:
        log.warning("get_best_model failed (%s) – falling back to default routing", exc)
        return None


async def call_with_fallback(
    messages: list[dict],
    api_keys: dict[str, str],
    providers: Optional[list] = None,
) -> tuple[dict, Provider]:
    """Try providers cheapest-first. Returns (result, used_provider).

    Identical message payloads are served from an in-process cache (TTL=5 min)
    to avoid redundant API calls and save tokens.
    """
    ck = _cache_key(messages)
    now = time.time()
    if ck in _response_cache:
        cached_result, cached_provider, ts = _response_cache[ck]
        if now - ts < _CACHE_TTL:
            return cached_result, cached_provider

    _evict_expired()

    errors: list[str] = []
    for provider in _sorted_providers(providers):
        key = api_keys.get(provider.name)
        if not key:
            errors.append(f"{provider.name}: no api_key")
            continue
        try:
            result = await provider.chat(messages, api_key=key)
            _response_cache[ck] = (result, provider, time.time())
            return result, provider
        except httpx.HTTPStatusError as e:
            errors.append(f"{provider.name}: HTTP {e.response.status_code}")
            if e.response.status_code not in FALLBACK_STATUS_CODES:
                raise
        except Exception as e:
            errors.append(f"{provider.name}: {e}")
    raise RuntimeError(f"All providers failed: {errors}")
