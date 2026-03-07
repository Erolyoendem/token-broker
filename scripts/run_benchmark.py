#!/usr/bin/env python3
"""
Weekly benchmark runner – executes all tasks against all providers,
stores results in Supabase, and updates the in-memory matrix cache.

Usage:
    python scripts/run_benchmark.py [--providers nvidia deepseek] [--tasks all]

Can also be called directly by APScheduler from main.py.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Allow running from project root or scripts/
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_benchmark.api import update_cache
from llm_benchmark.matrix import MatrixBuilder
from llm_benchmark.runner import BenchmarkRunner
from llm_benchmark.store import BenchmarkStore
from llm_benchmark.tasks import TASK_MAP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("run_benchmark")


def run(providers: list[str], task_ids: list[str] | None = None) -> dict:
    proxy_url = os.getenv("TOKENBROKER_URL", "http://localhost:8000")
    api_key   = os.getenv("TOKENBROKER_KEY", "")

    store = BenchmarkStore()
    if not store.ensure_table():
        log.warning("benchmark_results table not found. Results won't be persisted.")

    runner = BenchmarkRunner(
        proxy_url=proxy_url,
        api_key=api_key,
        providers=providers,
    )

    log.info("Starting benchmark: %d provider(s), %d task(s)",
             len(providers), len(task_ids or list(TASK_MAP)))

    runs = runner.run_all(task_ids=task_ids)

    # Persist each result
    for run_obj in runs:
        for result in run_obj.results:
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

    # Build and cache matrix
    matrix = MatrixBuilder().build(runs)
    update_cache(matrix)

    summary = matrix.as_dict()
    log.info("Benchmark complete. Best provider: %s (score=%.3f)",
             matrix.providers[0].provider if matrix.providers else "none",
             matrix.providers[0].composite_score if matrix.providers else 0.0)

    # Print summary table
    print("\n── LLM Benchmark Matrix ───────────────────────────────────")
    print(f"{'Provider':<12} {'Accuracy':>9} {'Latency':>9} {'Cost/1M':>9} {'Score':>8}")
    print("─" * 53)
    for p in summary.get("providers", []):
        print(
            f"{p['provider']:<12} "
            f"{p['overall_accuracy']:>9.1%} "
            f"{p['avg_latency_s']:>8.2f}s "
            f"${p['cost_per_1m_usd']:>8.2f} "
            f"{p['composite_score']:>8.3f}"
        )
    print("─" * 53)
    print(f"Generated: {summary.get('generated_at', '')}\n")
    return summary


def weekly_job() -> None:
    """Entry point for APScheduler."""
    providers = os.getenv("BENCHMARK_PROVIDERS", "nvidia,deepseek").split(",")
    try:
        run([p.strip() for p in providers if p.strip()])
    except Exception as e:
        log.error("Weekly benchmark job failed: %s", e)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run LLM benchmark")
    parser.add_argument(
        "--providers", nargs="+",
        default=os.getenv("BENCHMARK_PROVIDERS", "nvidia,deepseek").split(","),
        help="Provider names (default: nvidia deepseek)",
    )
    parser.add_argument(
        "--tasks", nargs="*",
        default=None,
        help="Task IDs to run (default: all)",
    )
    args = parser.parse_args()
    run(args.providers, task_ids=args.tasks or None)
