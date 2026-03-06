import pytest
from unittest.mock import AsyncMock, patch
import httpx

from app.router import call_with_fallback
from app.providers import NVIDIA_PROVIDER, DEEPSEEK_PROVIDER, Provider

MESSAGES = [{"role": "user", "content": "hi"}]
API_KEYS = {"nvidia": "nvidia-key", "deepseek": "deepseek-key"}
MOCK_RESPONSE = {"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 10}}
# Pass hardcoded providers so tests don't hit the DB
PROVIDERS = [NVIDIA_PROVIDER, DEEPSEEK_PROVIDER]


@pytest.mark.asyncio
async def test_nvidia_ok():
    with patch.object(NVIDIA_PROVIDER, "chat", new=AsyncMock(return_value=MOCK_RESPONSE)):
        result, provider = await call_with_fallback(MESSAGES, API_KEYS, providers=PROVIDERS)
    assert provider.name == "nvidia"
    assert result == MOCK_RESPONSE


@pytest.mark.asyncio
async def test_nvidia_fails_fallback_to_deepseek():
    error_response = AsyncMock()
    error_response.status_code = 429

    async def nvidia_fail(*a, **kw):
        raise httpx.HTTPStatusError("rate limited", request=None, response=error_response)

    with patch.object(NVIDIA_PROVIDER, "chat", new=nvidia_fail), \
         patch.object(DEEPSEEK_PROVIDER, "chat", new=AsyncMock(return_value=MOCK_RESPONSE)):
        result, provider = await call_with_fallback(MESSAGES, API_KEYS, providers=PROVIDERS)
    assert provider.name == "deepseek"
    assert result == MOCK_RESPONSE


@pytest.mark.asyncio
async def test_both_fail_raises_502_detail():
    error_response = AsyncMock()
    error_response.status_code = 503

    async def fail(*a, **kw):
        raise httpx.HTTPStatusError("down", request=None, response=error_response)

    with patch.object(NVIDIA_PROVIDER, "chat", new=fail), \
         patch.object(DEEPSEEK_PROVIDER, "chat", new=fail):
        with pytest.raises(RuntimeError) as exc:
            await call_with_fallback(MESSAGES, API_KEYS, providers=PROVIDERS)
    assert "All providers failed" in str(exc.value)
    assert "nvidia" in str(exc.value)
    assert "deepseek" in str(exc.value)
