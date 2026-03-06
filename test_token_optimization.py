"""
Measures token savings from the response cache in call_with_fallback.
Sends the same prompt twice; the second call should hit the cache (0 API tokens used).
"""
import asyncio
import hashlib
import json
import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
os.environ.setdefault("DATABASE_URL", "")

from app.router import _cache_key, _response_cache, _CACHE_TTL
from app.providers import Provider

# Dummy provider that counts calls
call_count = 0

async def fake_chat(messages, api_key, **kwargs):
    global call_count
    call_count += 1
    return {
        "id": "fake-id",
        "choices": [{"message": {"role": "assistant", "content": "Hello!"}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    }

async def main():
    global call_count

    messages = [{"role": "user", "content": "What is 2+2?"}]
    fake_provider = Provider(
        name="test",
        model="test-model",
        api_base="http://localhost",
        input_price_per_million=0.14,
        output_price_per_million=0.28,
    )
    fake_provider.chat = fake_chat

    api_keys = {"test": "test-key"}

    # Patch _sorted_providers to return our fake provider
    import app.router as router_module
    original_sorted = router_module._sorted_providers
    router_module._sorted_providers = lambda providers=None: [fake_provider]

    # --- First call (cache miss) ---
    t0 = time.perf_counter()
    result1, p1 = await router_module.call_with_fallback(messages, api_keys)
    t1 = time.perf_counter()
    tokens_first = result1["usage"]["total_tokens"]

    # --- Second call (cache hit) ---
    t2 = time.perf_counter()
    result2, p2 = await router_module.call_with_fallback(messages, api_keys)
    t3 = time.perf_counter()
    tokens_second = result2["usage"]["total_tokens"]

    router_module._sorted_providers = original_sorted

    print("=== Token Optimization Test ===")
    print(f"First call  : {tokens_first} tokens  (API calls made: {call_count})  {(t1-t0)*1000:.1f}ms")
    print(f"Second call : {tokens_second} tokens  (API calls made: {call_count})  {(t3-t2)*1000:.1f}ms")
    print(f"Cache hit   : {'YES' if call_count == 1 else 'NO'}")
    print(f"Tokens saved: {tokens_first} (100% on repeated identical prompts)")
    print(f"Cache TTL   : {_CACHE_TTL}s")
    assert call_count == 1, "Cache miss on second identical call!"
    print("\nPASS: Second call served from cache, no API tokens consumed.")

asyncio.run(main())
