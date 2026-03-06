from __future__ import annotations
from typing import Optional
import hashlib
import json
import time
import httpx
from app.providers import Provider, ALL_PROVIDERS
from app.db_providers import get_active_providers_from_db

FALLBACK_STATUS_CODES = {429, 401, 403, 500, 502, 503, 504}

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
