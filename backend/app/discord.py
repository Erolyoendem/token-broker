from __future__ import annotations
import os
import httpx


WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")


async def notify(message: str) -> None:
    """Send a message to the Discord webhook (fire-and-forget)."""
    if not WEBHOOK_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(WEBHOOK_URL, json={"content": message})
    except Exception:
        pass  # never block the main request
