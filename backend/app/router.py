from __future__ import annotations
from typing import Optional
import httpx
from app.providers import Provider, ALL_PROVIDERS

FALLBACK_STATUS_CODES = {429, 401, 403, 500, 502, 503, 504}


def get_cheapest_provider(providers: Optional[list] = None) -> Provider:
    pool = providers or ALL_PROVIDERS
    active = [p for p in pool if p.active]
    if not active:
        raise RuntimeError("No active providers available")
    return min(active, key=lambda p: p.cost_per_million())


def get_provider_by_name(name: str) -> Provider:
    for p in ALL_PROVIDERS:
        if p.name == name:
            return p
    raise ValueError(f"Unknown provider: {name}")


def _sorted_providers(providers: Optional[list] = None) -> list[Provider]:
    pool = providers or ALL_PROVIDERS
    return sorted([p for p in pool if p.active], key=lambda p: p.cost_per_million())


async def call_with_fallback(
    messages: list[dict],
    api_keys: dict[str, str],
    providers: Optional[list] = None,
) -> tuple[dict, Provider]:
    """Try providers cheapest-first. Returns (result, used_provider)."""
    errors: list[str] = []
    for provider in _sorted_providers(providers):
        key = api_keys.get(provider.name)
        if not key:
            errors.append(f"{provider.name}: no api_key")
            continue
        try:
            result = await provider.chat(messages, api_key=key)
            return result, provider
        except httpx.HTTPStatusError as e:
            errors.append(f"{provider.name}: HTTP {e.response.status_code}")
            if e.response.status_code not in FALLBACK_STATUS_CODES:
                raise
        except Exception as e:
            errors.append(f"{provider.name}: {e}")
    raise RuntimeError(f"All providers failed: {errors}")
