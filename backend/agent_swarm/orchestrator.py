"""
Orchestrator – Meta-cognition engine for the TokenBroker agent swarm.

Responsibilities:
  1. Distribute Ruby files across GenerationAgents via asyncio.Queue
  2. Route each result through an EvaluationAgent
  3. Persist records to SwarmMemory (including prompt variant feedback)
  4. Detect capability gaps: files that repeatedly fail get flagged
  5. Report aggregated metrics after each run

The "reinforcement learning" signal flows as:
  conversion_ok?  → memory.record_prompt_result(variant, success)
  eval_score      → memory.add_conversion(score=...)

Over multiple runs, best_prompt_variant() steers generation toward the
best-performing prompt variant (epsilon-greedy selection in GenerationAgent).
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import aiohttp
from dotenv import load_dotenv

from .generation_agent import GenerationAgent
from .evaluation_agent import EvaluationAgent
from .memory import SwarmMemory

load_dotenv()
DISCORD_URL = os.getenv("DISCORD_WEBHOOK_URL", "")


async def _discord(session: aiohttp.ClientSession, msg: str) -> None:
    if not DISCORD_URL:
        return
    try:
        await session.post(
            DISCORD_URL,
            json={"content": msg},
            timeout=aiohttp.ClientTimeout(total=5),
        )
    except Exception:
        pass


async def _process_one(
    task: dict[str, Any],
    gen_agent: GenerationAgent,
    eval_agent: EvaluationAgent,
    memory: SwarmMemory,
    results: list[dict],
    lock: asyncio.Lock,
    session: aiohttp.ClientSession,
) -> None:
    filename = task["filename"]
    ruby_code = task["ruby_code"]

    # Generation phase
    gen_result = await gen_agent.run(task)

    # Evaluation phase (always runs, even if generation failed)
    eval_task = {
        "filename": filename,
        "ruby_code": ruby_code,
        "python_code": gen_result.get("python_code", ""),
    }
    eval_result = await eval_agent.run(eval_task)

    score = eval_result["score"] if gen_result["ok"] else 0.0
    elapsed = gen_result["elapsed_s"] + eval_result.get("elapsed_s", 0)

    memory.add_conversion(
        filename=filename,
        ruby_code=ruby_code,
        python_code=gen_result.get("python_code", ""),
        score=score,
        tokens=gen_result.get("tokens", 0),
        elapsed_s=elapsed,
        prompt_variant=gen_result.get("prompt_variant", "unknown"),
        error=gen_result.get("error", "") or eval_result.get("feedback", ""),
    )

    combined = {
        "filename": filename,
        "agent": gen_agent.agent_id,
        "ok": gen_result["ok"] and eval_result["ok"],
        "score": score,
        "tokens": gen_result.get("tokens", 0),
        "elapsed_s": elapsed,
        "prompt_variant": gen_result.get("prompt_variant", ""),
        "feedback": eval_result.get("feedback", ""),
        "python_code": gen_result.get("python_code", ""),
        "error": gen_result.get("error", ""),
    }
    async with lock:
        results.append(combined)

    status = "OK" if combined["ok"] else "ERR"
    log_msg = (
        f"[Swarm] {gen_agent.agent_id} {status} `{filename}` "
        f"score={score:.2f} | {gen_result.get('tokens', 0)} tok | {elapsed:.2f}s "
        f"| variant={gen_result.get('prompt_variant', '?')}"
    )
    await _discord(session, log_msg)
    print(f"  {log_msg}")


async def _worker(
    worker_id: int,
    queue: asyncio.Queue,
    memory: SwarmMemory,
    results: list[dict],
    lock: asyncio.Lock,
    session: aiohttp.ClientSession,
) -> dict:
    gen_agent = GenerationAgent(f"gen-{worker_id}", memory)
    eval_agent = EvaluationAgent(f"eval-{worker_id}")
    await gen_agent.setup()

    while True:
        try:
            task: dict = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        try:
            await _process_one(task, gen_agent, eval_agent, memory, results, lock, session)
        except Exception as exc:
            # Fallback: agent crash doesn't stop the swarm
            print(f"  [Worker-{worker_id}] CRASH on {task['filename']}: {exc}")
            async with lock:
                results.append({
                    "filename": task["filename"],
                    "agent": f"gen-{worker_id}",
                    "ok": False,
                    "score": 0.0,
                    "error": f"worker crash: {exc}",
                })
        queue.task_done()

    await gen_agent.teardown()
    return gen_agent.stats


class Orchestrator:
    """
    High-level entry point for training runs and single conversions.

    Parameters
    ----------
    memory   : SwarmMemory instance (shared across runs)
    workers  : number of parallel generation agents
    """

    def __init__(self, memory: SwarmMemory, workers: int = 5) -> None:
        self.memory = memory
        self.workers = workers

    # ── Meta-cognition: capability gap detection ───────────────────────────────

    def detect_gaps(self) -> list[str]:
        """Return filenames that have failed more than once."""
        from collections import Counter
        counts: Counter = Counter()
        for c in self.memory.recent_conversions(200):
            if c["score"] < 0.5:
                counts[c["filename"]] += 1
        return [fn for fn, n in counts.items() if n >= 2]

    # ── Training run ───────────────────────────────────────────────────────────

    async def train(self, ruby_dir: Path) -> dict[str, Any]:
        """
        Run the full swarm over all *.rb files in ruby_dir.
        Returns a run summary dict.
        """
        ruby_files = sorted(ruby_dir.glob("*.rb"))
        if not ruby_files:
            return {"error": f"No .rb files in {ruby_dir}"}

        queue: asyncio.Queue = asyncio.Queue()
        for rb in ruby_files:
            await queue.put({"filename": rb.name, "ruby_code": rb.read_text(encoding="utf-8")})

        results: list[dict] = []
        lock = asyncio.Lock()
        t_start = time.perf_counter()

        connector = aiohttp.TCPConnector(limit=self.workers)
        async with aiohttp.ClientSession(connector=connector) as session:
            worker_tasks = [
                asyncio.create_task(
                    _worker(wid + 1, queue, self.memory, results, lock, session)
                )
                for wid in range(self.workers)
            ]
            agent_stats = await asyncio.gather(*worker_tasks)

            total_elapsed = round(time.perf_counter() - t_start, 2)
            ok = [r for r in results if r["ok"]]
            summary = {
                "files": len(ruby_files),
                "ok": len(ok),
                "errors": len(results) - len(ok),
                "avg_score": round(sum(r["score"] for r in results) / max(len(results), 1), 3),
                "total_tokens": sum(r.get("tokens", 0) for r in results),
                "elapsed_s": total_elapsed,
                "gaps": self.detect_gaps(),
                "prompt_stats": self.memory.prompt_stats(),
                "agent_stats": list(agent_stats),
            }
            self.memory.add_run_summary(summary)

            final_msg = (
                f"[Swarm] Training done: {len(ok)}/{len(ruby_files)} OK "
                f"| avg_score={summary['avg_score']} "
                f"| {summary['total_tokens']} tok | {total_elapsed}s"
            )
            await _discord(session, final_msg)

        return summary

    # ── Single conversion ──────────────────────────────────────────────────────

    async def convert_one(self, filename: str, ruby_code: str) -> dict[str, Any]:
        """Convert a single Ruby snippet using the best available prompt."""
        results: list[dict] = []
        lock = asyncio.Lock()

        connector = aiohttp.TCPConnector(limit=1)
        async with aiohttp.ClientSession(connector=connector) as session:
            gen_agent = GenerationAgent("gen-single", self.memory, epsilon=0.0)
            eval_agent = EvaluationAgent("eval-single")
            await gen_agent.setup()
            task = {"filename": filename, "ruby_code": ruby_code}
            await _process_one(task, gen_agent, eval_agent, self.memory, results, lock, session)
            await gen_agent.teardown()

        return results[0] if results else {"ok": False, "error": "no result"}
