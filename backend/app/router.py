from typing import Optional
from app.providers import Provider, ALL_PROVIDERS


def get_cheapest_provider(providers: Optional[list] = None) -> Provider:
    """Return the active provider with the lowest average cost per million tokens."""
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
