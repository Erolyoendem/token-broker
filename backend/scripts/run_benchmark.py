"""
Weekly benchmark job – runs all LLM benchmark tasks against configured providers
and stores results via BenchmarkStore.

Scheduled in main.py lifespan (Monday 02:00 UTC via APScheduler).
Can also be run manually:
    cd backend && python -m scripts.run_benchmark
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def weekly_job() -> None:
    """APScheduler entry point: run benchmark suite and persist results."""
    try:
        from llm_benchmark.runner import BenchmarkRunner, DEFAULT_PROVIDERS
        from llm_benchmark.matrix import MatrixBuilder
        from llm_benchmark.store import BenchmarkStore
        from llm_benchmark.api import update_cache

        proxy_url = os.getenv("TOKENBROKER_URL", "http://localhost:8000")
        api_key = os.getenv("TOKENBROKER_API_KEY", "")

        runner = BenchmarkRunner(proxy_url=proxy_url, api_key=api_key)
        store = BenchmarkStore()
        runs = runner.run_all()

        for run in runs:
            for result in run.results:
                store.insert_result(
                    task_id=result.task_id,
                    category=result.category,
                    provider=result.provider,
                    passed=result.passed,
                    response=result.response,
                    note=result.note,
                    latency_s=result.latency_s,
                    tokens_used=result.tokens_used,
                    error=result.error,
                )

        if runs:
            matrix = MatrixBuilder().build(runs)
            update_cache(matrix)
            log.info(
                "[benchmark] Weekly run complete. Providers: %s",
                [r.provider for r in runs],
            )
        else:
            log.warning("[benchmark] No runs produced – check provider config")

    except Exception as exc:
        log.error("[benchmark] Weekly job failed: %s", exc, exc_info=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    weekly_job()
