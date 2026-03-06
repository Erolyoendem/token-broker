from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import httpx
import os


@dataclass
class Provider:
    name: str
    model: str
    api_base: str
    input_price_per_million: float
    output_price_per_million: float
    cache_discount: float = 0.0
    active: bool = True

    def cost_per_million(self) -> float:
        """Weighted average cost (input + output) per 1M tokens."""
        return (self.input_price_per_million + self.output_price_per_million) / 2

    async def chat(self, messages: list[dict], api_key: str, **kwargs) -> dict:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self.model, "messages": messages, **kwargs}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.api_base}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()


NVIDIA_PROVIDER = Provider(
    name="nvidia",
    model="meta/llama-3.1-70b-instruct",
    api_base="https://integrate.api.nvidia.com/v1",
    input_price_per_million=0.0,   # free tier credits
    output_price_per_million=0.0,
)

DEEPSEEK_PROVIDER = Provider(
    name="deepseek",
    model="deepseek-chat",
    api_base="https://api.deepseek.com/v1",
    input_price_per_million=0.14,
    output_price_per_million=0.28,
)

ALL_PROVIDERS: list[Provider] = [NVIDIA_PROVIDER, DEEPSEEK_PROVIDER]
