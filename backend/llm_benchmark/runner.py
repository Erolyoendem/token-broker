"""
Benchmark runner – executes tasks against configured LLM providers
and records latency, token usage, and accuracy.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .tasks import BenchmarkTask, TASKS

log = logging.getLogger(__name__)

# Providers the runner knows about. Add entries here to test more models.
DEFAULT_PROVIDERS = ["nvidia", "deepseek"]


@dataclass
class RunResult:
    task_id: str
    category: str
    provider: str
    passed: bool
    response: str
    note: str
    latency_s: float
    tokens_used: int
    error: str = ""


@dataclass
class BenchmarkRun:
    provider: str
    results: list[RunResult] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.passed) / len(self.results)

    @property
    def avg_latency(self) -> float:
        valid = [r.latency_s for r in self.results if not r.error]
        return round(sum(valid) / len(valid), 3) if valid else 0.0

    @property
    def total_tokens(self) -> int:
        return sum(r.tokens_used for r in self.results)


class BenchmarkRunner:
    def __init__(
        self,
        proxy_url: str = "http://localhost:8000",
        api_key: str = "",
        providers: Optional[list[str]] = None,
        timeout: float = 45.0,
    ):
        self._url = proxy_url.rstrip("/")
        self._key = api_key
        self._providers = providers or DEFAULT_PROVIDERS
        self._timeout = timeout

    # ── Public ────────────────────────────────────────────────────────────────

    def run_all(self, task_ids: Optional[list[str]] = None) -> list[BenchmarkRun]:
        """Run all (or selected) tasks against all configured providers."""
        tasks = [t for t in TASKS if task_ids is None or t.id in task_ids]
        runs = []
        for provider in self._providers:
            run = BenchmarkRun(provider=provider)
            for task in tasks:
                result = self._run_task(task, provider)
                run.results.append(result)
                log.info(
                    "[%s] %s → %s (%.2fs, %d tok)",
                    provider, task.id,
                    "PASS" if result.passed else "FAIL",
                    result.latency_s, result.tokens_used,
                )
            runs.append(run)
        return runs

    def run_task(self, task: BenchmarkTask, provider: str) -> RunResult:
        return self._run_task(task, provider)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run_task(self, task: BenchmarkTask, provider: str) -> RunResult:
        start = time.perf_counter()
        try:
            response, tokens = self._call(task.prompt, provider)
            latency = round(time.perf_counter() - start, 3)
            passed, note = task.validate(response)
            return RunResult(
                task_id=task.id,
                category=task.category,
                provider=provider,
                passed=passed,
                response=response[:500],
                note=note,
                latency_s=latency,
                tokens_used=tokens,
            )
        except Exception as exc:
            latency = round(time.perf_counter() - start, 3)
            log.warning("Task %s / provider %s failed: %s", task.id, provider, exc)
            return RunResult(
                task_id=task.id,
                category=task.category,
                provider=provider,
                passed=False,
                response="",
                note="",
                latency_s=latency,
                tokens_used=0,
                error=str(exc),
            )

    def _call(self, prompt: str, provider: str) -> tuple[str, int]:
        """POST to TokenBroker's /v1/chat/completions with forced provider."""
        resp = httpx.post(
            f"{self._url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
            },
            json={
                "messages": [{"role": "user", "content": prompt}],
                "provider": provider,
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return content, tokens
