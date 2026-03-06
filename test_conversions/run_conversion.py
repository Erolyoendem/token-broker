#!/usr/bin/env python3
"""
TokenBroker – Ruby→Python Batch Converter + Quality Evaluator
Reads all .rb files, converts via /v1/chat/completions, saves .py files,
runs syntax check + flake8, logs to results.csv, generates evaluation.md.
"""
import csv
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

PROXY_URL = os.getenv("TOKENBROKER_URL", "http://localhost:8000")
API_KEY   = os.getenv("TOKENBROKER_KEY", "tkb_test_123")
DIR       = Path(__file__).parent
RESULTS   = DIR / "results.csv"
EVAL_MD   = DIR / "evaluation.md"

SYSTEM_PROMPT = (
    "You are a Ruby-to-Python code converter. "
    "Output only valid Python code with no explanation, no markdown fences. "
    "Use idiomatic Python 3: dataclasses or plain classes, list comprehensions, "
    "f-strings. Do not include 'require' statements."
)

FLAKE8 = (
    sys.executable, "-m", "flake8",
    "--max-line-length=100",
    "--extend-ignore=E302,E303,W391",
)


# ── Conversion ────────────────────────────────────────────────────────────────

def convert(ruby_code: str) -> tuple[str, int]:
    resp = httpx.post(
        f"{PROXY_URL}/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={"messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": f"Convert to Python:\n\n{ruby_code}"},
        ]},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    content = re.sub(r"^```[a-z]*\n?", "", content).rstrip("`").strip()
    tokens = data.get("usage", {}).get("total_tokens", 0)
    return content, tokens


# ── Quality evaluation ────────────────────────────────────────────────────────

def check_syntax(py_file: Path) -> tuple[bool, str]:
    """Run `python -m py_compile`. Returns (ok, error_msg)."""
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(py_file)],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return True, ""
    msg = (result.stderr or result.stdout).strip().splitlines()[0]
    return False, msg


def check_flake8(py_file: Path) -> tuple[str, list[str]]:
    """Run flake8. Returns (grade, issues)."""
    result = subprocess.run(
        [*FLAKE8, str(py_file)],
        capture_output=True, text=True,
    )
    issues = [
        line.split(":")[-1].strip()
        for line in result.stdout.strip().splitlines()
        if line.strip()
    ]
    # Grade: A (0 issues), B (1-2), C (3-5), D (6+)
    n = len(issues)
    grade = "A" if n == 0 else "B" if n <= 2 else "C" if n <= 5 else "D"
    return grade, issues


def evaluate_quality(original_file: Path, converted_file: Path) -> dict:
    """
    Evaluate a converted Python file.
    Returns a dict with: syntax_ok, syntax_error, flake8_grade,
                         flake8_issues, flake8_count, quality_score.
    quality_score: 0-100 composite (syntax 50 pts + flake8 50 pts).
    """
    if not converted_file.exists():
        return {
            "syntax_ok": False,
            "syntax_error": "file not found",
            "flake8_grade": "F",
            "flake8_issues": [],
            "flake8_count": 0,
            "quality_score": 0,
        }

    syntax_ok, syntax_error = check_syntax(converted_file)
    flake8_grade, flake8_issues = check_flake8(converted_file)

    syntax_pts  = 50 if syntax_ok else 0
    flake8_pts  = {"A": 50, "B": 40, "C": 25, "D": 10, "F": 0}.get(flake8_grade, 0)
    quality_score = syntax_pts + flake8_pts

    return {
        "syntax_ok":     syntax_ok,
        "syntax_error":  syntax_error,
        "flake8_grade":  flake8_grade,
        "flake8_issues": flake8_issues,
        "flake8_count":  len(flake8_issues),
        "quality_score": quality_score,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ruby_files = sorted(DIR.glob("*.rb"))
    if not ruby_files:
        print("No .rb files found.")
        return

    rows = []
    for rb in ruby_files:
        start = time.time()
        py_out = rb.with_suffix(".py")
        conv_status = "OK"
        tokens = 0

        try:
            python_code, tokens = convert(rb.read_text())
            py_out.write_text(python_code + "\n")
            elapsed = round(time.time() - start, 2)
            print(f"[OK]  {rb.name} → {py_out.name} ({tokens} tokens, {elapsed}s)")
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            conv_status = f"ERROR: {e}"
            print(f"[ERR] {rb.name}: {e}")

        quality = evaluate_quality(rb, py_out)

        row = {
            "file":          rb.name,
            "tokens":        tokens,
            "elapsed_s":     elapsed,
            "conv_status":   conv_status,
            "syntax_ok":     quality["syntax_ok"],
            "flake8_grade":  quality["flake8_grade"],
            "flake8_count":  quality["flake8_count"],
            "quality_score": quality["quality_score"],
            "errors":        "; ".join(quality["flake8_issues"][:3]),
        }
        rows.append({**row, "_quality": quality})

        sym = "✓" if quality["syntax_ok"] else "✗"
        print(
            f"      syntax:{sym}  flake8:{quality['flake8_grade']}  "
            f"score:{quality['quality_score']}/100"
        )

    # CSV
    csv_fields = [
        "file", "tokens", "elapsed_s", "conv_status",
        "syntax_ok", "flake8_grade", "flake8_count", "quality_score", "errors",
    ]
    with open(RESULTS, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in csv_fields})

    # evaluation.md
    write_evaluation_md(rows)

    total_tokens = sum(r["tokens"] for r in rows)
    avg_score    = round(sum(r["quality_score"] for r in rows) / len(rows), 1)
    print(f"\nResults  → {RESULTS}")
    print(f"Eval     → {EVAL_MD}")
    print(f"Tokens   : {total_tokens}")
    print(f"Avg score: {avg_score}/100")


def write_evaluation_md(rows: list[dict]):
    lines = ["# Ruby→Python Konvertierung – Qualitätsbericht\n"]
    lines.append(f"Generiert: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}\n")

    # Summary table
    lines.append("## Ergebnisse\n")
    lines.append(
        "| Datei | Tokens | Zeit (s) | Syntax | Flake8 | Score | Fehler |\n"
        "|-------|--------|----------|--------|--------|-------|--------|\n"
    )
    for r in rows:
        q   = r["_quality"]
        syn = "✓" if q["syntax_ok"] else "✗"
        issues_short = "; ".join(q["flake8_issues"][:2]) if q["flake8_issues"] else "–"
        if len(issues_short) > 60:
            issues_short = issues_short[:57] + "..."
        lines.append(
            f"| {r['file']} | {r['tokens']} | {r['elapsed_s']} "
            f"| {syn} | {q['flake8_grade']} | {r['quality_score']}/100 "
            f"| {issues_short} |\n"
        )

    # Averages
    ok_count  = sum(1 for r in rows if r["_quality"]["syntax_ok"])
    avg_score = round(sum(r["quality_score"] for r in rows) / len(rows), 1)
    lines.append(f"\n**Syntax OK:** {ok_count}/{len(rows)}  \n")
    lines.append(f"**Durchschnitts-Score:** {avg_score}/100\n")

    # Per-file details
    lines.append("\n## Detailanalyse\n")
    for r in rows:
        q = r["_quality"]
        lines.append(f"### {r['file']}\n")
        lines.append(f"- **Konvertierung:** {r['conv_status']}\n")
        lines.append(f"- **Syntax:** {'OK' if q['syntax_ok'] else 'FEHLER – ' + q['syntax_error']}\n")
        lines.append(f"- **Flake8-Note:** {q['flake8_grade']} ({q['flake8_count']} Probleme)\n")
        if q["flake8_issues"]:
            for issue in q["flake8_issues"][:5]:
                lines.append(f"  - {issue}\n")
        lines.append(f"- **Quality-Score:** {r['quality_score']}/100\n\n")

    # Recommendations
    lines.append("## Prompt-Optimierungsvorschläge\n\n")
    low_scores = [r for r in rows if r["quality_score"] < 80]
    if not low_scores:
        lines.append("Alle Dateien erzielen ≥80/100 – kein dringender Handlungsbedarf.\n\n")
    else:
        lines.append(f"{len(low_scores)} Datei(en) unter 80 Punkten:\n\n")
    lines += [
        "1. **Zeilenlaenge:** `max-line-length=100` im Prompt explizit nennen, "
        "z.B. *'Wrap lines at 100 characters'*.\n",
        "2. **Leerzeilen:** Prompt um *'Add exactly two blank lines between top-level "
        "definitions'* ergänzen.\n",
        "3. **Importe:** *'Place all imports at the top of the file'* hinzufügen, "
        "um E402-Fehler zu vermeiden.\n",
        "4. **Typ-Annotierungen:** *'Add type hints for function signatures'* "
        "verbessert Lesbarkeit und flake8-Score.\n",
        "5. **Ungenutzte Variablen:** *'Remove unused variables and imports'* "
        "reduziert F401/F841-Warnungen.\n",
    ]

    EVAL_MD.write_text("".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
