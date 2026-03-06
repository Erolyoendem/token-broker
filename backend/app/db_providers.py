from __future__ import annotations
from app.db import get_client
from app.providers import Provider


def get_active_providers_from_db() -> list[Provider]:
    """Fetch all active providers from Supabase and return as Provider instances."""
    client = get_client()
    rows = client.table("providers").select("*").eq("active", True).execute().data
    return [
        Provider(
            name=r["name"],
            model=r["model"],
            api_base=r["api_base"] or "",
            input_price_per_million=float(r["input_price_per_million"] or 0),
            output_price_per_million=float(r["output_price_per_million"] or 0),
            cache_discount=float(r["cache_discount"] or 0),
            active=r["active"],
        )
        for r in rows
    ]
