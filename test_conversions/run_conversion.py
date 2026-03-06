#!/usr/bin/env python3
"""
TokenBroker – Ruby→Python Batch Converter
Reads all .rb files, converts via /v1/chat/completions, saves .py files, logs to results.csv.
"""
import csv
import os
import re
import time
from pathlib import Path
import httpx

PROXY_URL = os.getenv("TOKENBROKER_URL", "http://localhost:8000")
API_KEY   = os.getenv("TOKENBROKER_KEY", "tkb_test_123")
DIR       = Path(__file__).parent
RESULTS   = DIR / "results.csv"

SYSTEM_PROMPT = (
    "You are a Ruby-to-Python code converter. "
    "Output only valid Python code with no explanation, no markdown fences."
)


def convert(ruby_code: str) -> tuple[str, int]:
    resp = httpx.post(
        f"{PROXY_URL}/v1/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={"messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": f"Convert to Python:\n\n{ruby_code}"},
        ]},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    # Strip markdown fences if model adds them anyway
    content = re.sub(r"^```[a-z]*\n?", "", content).rstrip("`").strip()
    tokens = data.get("usage", {}).get("total_tokens", 0)
    return content, tokens


def main():
    ruby_files = sorted(DIR.glob("*.rb"))
    if not ruby_files:
        print("No .rb files found.")
        return

    rows = []
    for rb in ruby_files:
        start = time.time()
        try:
            python_code, tokens = convert(rb.read_text())
            out = rb.with_suffix(".py")
            out.write_text(python_code + "\n")
            elapsed = round(time.time() - start, 2)
            status = "OK"
            print(f"[OK]  {rb.name} → {out.name} ({tokens} tokens, {elapsed}s)")
        except Exception as e:
            tokens, elapsed, status = 0, round(time.time() - start, 2), f"ERROR: {e}"
            print(f"[ERR] {rb.name}: {e}")
        rows.append({"file": rb.name, "tokens": tokens, "elapsed_s": elapsed, "status": status})

    with open(RESULTS, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "tokens", "elapsed_s", "status"])
        w.writeheader()
        w.writerows(rows)

    print(f"\nResults saved to {RESULTS}")
    print(f"Total tokens: {sum(r['tokens'] for r in rows)}")


if __name__ == "__main__":
    main()
