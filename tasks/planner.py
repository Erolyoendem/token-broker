#!/usr/bin/env python3
"""
tasks/planner.py – Parst NEXT_SESSION.md und erzeugt todo.md mit Checkboxen.

Usage:
    python tasks/planner.py [--next NEXT_SESSION_PATH] [--out TODO_PATH]
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
DEFAULT_NEXT = ROOT / "NEXT_SESSION.md"
DEFAULT_TODO  = ROOT / "tasks" / "todo.md"


# ── Parser ─────────────────────────────────────────────────────────────────────

def parse_next_session(text: str) -> tuple[list[dict], list[str]]:
    """
    Returns:
        tabs  – list of {id, label, status, done}
        open_ – list of open action strings from the OFFEN section
    """
    tabs: list[dict] = []
    open_: list[str] = []

    # 1. Status table
    table_re = re.compile(
        r"^\|\s*(?P<id>Tab[\s\w]+?\d*[\w]*)\s*\|\s*(?P<label>[^|]+?)\s*\|\s*(?P<status>[^|]+?)\s*\|",
        re.MULTILINE,
    )
    for m in table_re.finditer(text):
        status = m.group("status").strip()
        done = bool(re.search(r"\bOK\b|✅|Fertig", status, re.IGNORECASE))
        tabs.append(
            {
                "id": m.group("id").strip(),
                "label": m.group("label").strip(),
                "status": status,
                "done": done,
            }
        )

    # 2. OFFEN section – numbered items
    offen_block = re.search(r"## OFFEN.*?(?=\n## |\Z)", text, re.DOTALL)
    if offen_block:
        for line in offen_block.group(0).splitlines():
            m = re.match(r"^\d+\.\s+(.+)", line.strip())
            if m:
                open_.append(m.group(1).strip())

    return tabs, open_


def generate_todo(tabs: list[dict], open_items: list[str]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# TokenBroker – TODO",
        f"> Automatisch generiert aus NEXT_SESSION.md am {now}",
        "",
        "## Tabs",
        "",
    ]

    for t in tabs:
        checkbox = "[x]" if t["done"] else "[ ]"
        lines.append(f"- {checkbox} **{t['id']}** – {t['label']}  _{t['status']}_")

    if open_items:
        lines += ["", "## Offene Aufgaben", ""]
        for item in open_items:
            lines.append(f"- [ ] {item}")

    lines += ["", "---", f"_Generiert: {now}_", ""]
    return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate todo.md from NEXT_SESSION.md")
    parser.add_argument("--next", default=str(DEFAULT_NEXT), help="Path to NEXT_SESSION.md")
    parser.add_argument("--out",  default=str(DEFAULT_TODO),  help="Output todo.md path")
    args = parser.parse_args()

    src = Path(args.next)
    dst = Path(args.out)

    if not src.exists():
        print(f"ERROR: {src} not found", file=sys.stderr)
        sys.exit(1)

    text = src.read_text(encoding="utf-8")
    tabs, open_items = parse_next_session(text)
    todo = generate_todo(tabs, open_items)

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(todo, encoding="utf-8")
    print(f"✓ {dst} written  ({len(tabs)} tabs, {len(open_items)} open items)")


if __name__ == "__main__":
    main()
