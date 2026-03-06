#!/usr/bin/env python3
"""
TokenBroker – Paralleler Agenten-Schwarm
========================================
Verteilt Ruby-Dateien ueber eine asyncio.Queue auf 5 parallele Worker-Agenten,
die jeweils den TokenBroker-Proxy fuer die LLM-Konvertierung nutzen.
Ergebnisse werden in swarm_results.json gespeichert, jede Konvertierung
wird via Discord-Webhook geloggt.

Nutzung:
    python agent_swarm.py [--input-dir swarm_input] [--workers 5]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

# ── Config ──────────────────────────────────────────────────────────────────────
load_dotenv(Path(__file__).parent / "backend" / ".env")

PROXY_URL      = "https://yondem-production.up.railway.app/v1/chat/completions"
API_KEY        = os.getenv("TOKENBROKER_KEY", "tkb_test_123")
DISCORD_URL    = os.getenv("DISCORD_WEBHOOK_URL", "")
NUM_WORKERS    = 5
RESULTS_FILE   = Path(__file__).parent / "swarm_results.json"
DEFAULT_INPUT  = Path(__file__).parent / "swarm_input"

SYSTEM_PROMPT = (
    "You are a Ruby-to-Python code converter. "
    "Output only valid Python code with no explanation, no markdown fences."
)

# ── Helpers ──────────────────────────────────────────────────────────────────────
def strip_fences(text: str) -> str:
    text = re.sub(r"^```[a-z]*\n?", "", text.strip())
    return text.rstrip("`").strip()


async def discord_log(session: aiohttp.ClientSession, message: str) -> None:
    if not DISCORD_URL:
        return
    try:
        await session.post(DISCORD_URL, json={"content": message}, timeout=aiohttp.ClientTimeout(total=5))
    except Exception:
        pass  # fire-and-forget, never block the swarm


async def convert_ruby(session: aiohttp.ClientSession, ruby_code: str) -> tuple[str, int]:
    """Call TokenBroker proxy and return (python_code, total_tokens)."""
    payload = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": f"Convert to Python:\n\n{ruby_code}"},
        ]
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type":  "application/json",
    }
    async with session.post(
        PROXY_URL, json=payload, headers=headers,
        timeout=aiohttp.ClientTimeout(total=90),
    ) as resp:
        resp.raise_for_status()
        data = await resp.json()

    content = data["choices"][0]["message"]["content"]
    tokens  = data.get("usage", {}).get("total_tokens", 0)
    return strip_fences(content), tokens


# ── Worker ───────────────────────────────────────────────────────────────────────
async def worker(
    worker_id: int,
    queue: asyncio.Queue,
    results: list,
    session: aiohttp.ClientSession,
    lock: asyncio.Lock,
) -> None:
    print(f"  [Agent-{worker_id}] gestartet")
    while True:
        try:
            rb_path: Path = queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        ruby_code = rb_path.read_text(encoding="utf-8")
        t0 = time.perf_counter()
        status = "OK"
        python_code = ""
        tokens = 0

        try:
            python_code, tokens = await convert_ruby(session, ruby_code)
            elapsed = round(time.perf_counter() - t0, 2)
            print(f"  [Agent-{worker_id}] OK  {rb_path.name} ({tokens} tok, {elapsed}s)")

            # Save converted file next to input
            out = rb_path.with_suffix(".py")
            out.write_text(python_code + "\n", encoding="utf-8")

            msg = (
                f"[TokenBroker Swarm] Agent-{worker_id} konvertiert: "
                f"`{rb_path.name}` → `{out.name}` | {tokens} Token | {elapsed}s"
            )
            await discord_log(session, msg)

        except Exception as exc:
            elapsed = round(time.perf_counter() - t0, 2)
            status = f"ERROR: {exc}"
            print(f"  [Agent-{worker_id}] ERR {rb_path.name}: {exc}")

        result = {
            "file":      rb_path.name,
            "agent":     worker_id,
            "status":    status,
            "tokens":    tokens,
            "elapsed_s": elapsed,
            "python_code": python_code[:500] if python_code else "",
        }
        async with lock:
            results.append(result)

        queue.task_done()

    print(f"  [Agent-{worker_id}] fertig (Queue leer)")


# ── Main ─────────────────────────────────────────────────────────────────────────
async def main(input_dir: Path, num_workers: int) -> None:
    ruby_files = sorted(input_dir.glob("*.rb"))
    if not ruby_files:
        print(f"Keine .rb-Dateien in {input_dir}")
        return

    print(f"\nTokenBroker Agenten-Schwarm")
    print(f"  Eingabe-Verzeichnis : {input_dir}")
    print(f"  Ruby-Dateien        : {len(ruby_files)}")
    print(f"  Parallele Agenten   : {num_workers}")
    print(f"  Proxy               : {PROXY_URL}")
    print()

    queue: asyncio.Queue = asyncio.Queue()
    for rb in ruby_files:
        await queue.put(rb)

    results: list = []
    lock = asyncio.Lock()
    t_start = time.perf_counter()

    connector = aiohttp.TCPConnector(limit=num_workers)
    async with aiohttp.ClientSession(connector=connector) as session:
        workers = [
            asyncio.create_task(worker(wid + 1, queue, results, session, lock))
            for wid in range(num_workers)
        ]
        await asyncio.gather(*workers)

        total_elapsed = round(time.perf_counter() - t_start, 2)
        total_tokens  = sum(r["tokens"] for r in results)
        ok_count      = sum(1 for r in results if r["status"] == "OK")

        summary = {
            "run_at":          time.strftime("%Y-%m-%dT%H:%M:%S"),
            "files_total":     len(ruby_files),
            "files_ok":        ok_count,
            "files_error":     len(ruby_files) - ok_count,
            "total_tokens":    total_tokens,
            "total_elapsed_s": total_elapsed,
            "workers":         num_workers,
            "proxy":           PROXY_URL,
            "results":         sorted(results, key=lambda r: r["file"]),
        }

        RESULTS_FILE.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

        final_msg = (
            f"[TokenBroker Swarm] Durchlauf abgeschlossen: "
            f"{ok_count}/{len(ruby_files)} OK | "
            f"{total_tokens} Token gesamt | "
            f"{total_elapsed}s Gesamtlaufzeit | "
            f"{num_workers} Agenten"
        )
        await discord_log(session, final_msg)

    print(f"\nErgebnisse")
    print(f"  Gesamt       : {len(ruby_files)} Dateien")
    print(f"  Erfolgreich  : {ok_count}")
    print(f"  Fehler       : {len(ruby_files) - ok_count}")
    print(f"  Token gesamt : {total_tokens}")
    print(f"  Laufzeit     : {total_elapsed}s")
    print(f"  Output       : {RESULTS_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TokenBroker Agenten-Schwarm")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--workers",   type=int,  default=NUM_WORKERS)
    args = parser.parse_args()
    asyncio.run(main(args.input_dir, args.workers))
