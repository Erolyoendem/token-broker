#!/usr/bin/env python3
"""
Generate PROJECT_CONTEXT.md – a concise snapshot of the TokenBroker project
for use as context when starting new AI sessions or onboarding developers.

Usage:
    python scripts/generate_context.py [--output PATH]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
BACKEND = ROOT / "backend"
OUTPUT_DEFAULT = ROOT / "PROJECT_CONTEXT.md"


def _run(cmd: str, cwd: Path = ROOT) -> str:
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, cwd=cwd, timeout=10
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _count_lines(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except Exception:
        return 0


def _list_py_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.py")) if directory.exists() else []


def generate(output: Path = OUTPUT_DEFAULT) -> Path:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    git_log   = _run("git log --oneline -8")
    git_branch = _run("git branch --show-current")
    git_status = _run("git status --short")

    # Collect backend module list
    app_files = [f.relative_to(ROOT) for f in _list_py_files(BACKEND / "app")]
    test_files = [f.relative_to(ROOT) for f in _list_py_files(BACKEND / "tests")]

    # Skill list
    skills_dir = ROOT / "tasks" / "skills"
    skills = [f.stem for f in sorted(skills_dir.glob("*.md"))] if skills_dir.exists() else []

    # Read NEXT_SESSION.md
    next_session = ""
    ns_path = ROOT / "NEXT_SESSION.md"
    if not ns_path.exists():
        ns_path = Path.home() / "CLAUDE_BRIEFING" / "TokenBroker" / "NEXT_SESSION.md"
    if ns_path.exists():
        lines = ns_path.read_text(encoding="utf-8").splitlines()[:40]
        next_session = "\n".join(lines)

    lines: list[str] = [
        "# TokenBroker – Project Context",
        f"Generated: {now}  |  Branch: `{git_branch}`",
        "",
        "## Quick Links",
        "- Railway: https://yondem-production.up.railway.app",
        "- GitHub:  https://github.com/Erolyoendem/token-broker",
        "- Supabase: https://igbejdddgbvmgiankuev.supabase.co",
        "",
        "## Recent Commits",
        "```",
        git_log or "(no commits)",
        "```",
        "",
        "## Working Tree",
        "```",
        git_status or "(clean)",
        "```",
        "",
        "## Backend Modules (`backend/app/`)",
    ]

    for f in app_files:
        lines.append(f"- `{f}`  ({_count_lines(ROOT / f)} lines)")

    lines += [
        "",
        "## Test Files",
    ]
    for f in test_files:
        lines.append(f"- `{f}`")

    lines += [
        "",
        "## Available Skills (`/skill`)",
        ", ".join(f"`/{s}`" for s in skills) or "(none)",
        "",
        "## Next Session Notes",
        "",
        next_session or "(NEXT_SESSION.md not found)",
    ]

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate PROJECT_CONTEXT.md")
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    args = parser.parse_args()

    path = generate(args.output)
    lines = len(path.read_text().splitlines())
    print(f"[context] Done – {lines} lines written")
    print(f"[context] Path: {path}")


if __name__ == "__main__":
    main()
