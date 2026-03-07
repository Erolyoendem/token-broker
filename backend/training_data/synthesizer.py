"""
LLM-based code synthesizer.

Routes synthesis requests through TokenBroker's own /v1/chat/completions
endpoint, supporting NVIDIA, DeepSeek, and any configured provider.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from .language_pairs import LanguagePair

log = logging.getLogger(__name__)


@dataclass
class SynthesisResult:
    pair_id: str
    source_code: str
    target_code: str
    tokens_used: int
    provider: str
    prompt_version: str = "v1"


class Synthesizer:
    def __init__(
        self,
        proxy_url: str = "http://localhost:8000",
        api_key: str = "",
        provider: str | None = None,
        timeout: float = 60.0,
    ):
        self._url = proxy_url.rstrip("/")
        self._key = api_key
        self._provider = provider  # None = cheapest-first
        self._timeout = timeout

    def synthesize(self, source_code: str, pair: LanguagePair) -> SynthesisResult:
        """Convert source_code using the language pair's prompt."""
        prompt = pair.build_prompt(source_code)
        raw, tokens, provider = self._call_llm(prompt)
        target_code = pair.clean_llm_output(raw)
        return SynthesisResult(
            pair_id=pair.pair_id,
            source_code=source_code,
            target_code=target_code,
            tokens_used=tokens,
            provider=provider,
        )

    def synthesize_with_style(
        self, source_code: str, pair: LanguagePair, style_hint: str
    ) -> SynthesisResult:
        """Like synthesize() but injects an additional style constraint."""
        base_prompt = pair.build_prompt(source_code)
        prompt = f"{base_prompt}\n\nAdditional requirement: {style_hint}"
        raw, tokens, provider = self._call_llm(prompt)
        target_code = pair.clean_llm_output(raw)
        return SynthesisResult(
            pair_id=pair.pair_id,
            source_code=source_code,
            target_code=target_code,
            tokens_used=tokens,
            provider=provider,
            prompt_version="v1-styled",
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _call_llm(self, user_content: str) -> tuple[str, int, str]:
        """
        POST to /v1/chat/completions. Returns (content, total_tokens, provider).
        """
        payload: dict = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert code converter. "
                        "Output only code with no explanation."
                    ),
                },
                {"role": "user", "content": user_content},
            ]
        }
        if self._provider:
            payload["provider"] = self._provider

        resp = httpx.post(
            f"{self._url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens", 0)
        provider = data.get("provider", "unknown")
        return content, tokens, provider
