#!/usr/bin/env python3
"""
tasks/verifier.py – Führt Tests aus und hakt bestandene Tabs in NEXT_SESSION.md ab.

Usage:
    python tasks/verifier.py --tab "Tab D"
    python tasks/verifier.py --tab "Tab D" --test-cmd "pytest backend/tests/ -q"
    python tasks/verifier.py --all          # verify all pending tabs
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT         = Path(__file__).parent.parent
DEFAULT_NEXT = ROOT / "NEXT_SESSION.md"
DEFAULT_VENV = ROOT / "backend" / "venv" / "bin" / "pytest"
DEFAULT_TEST = f"pytest {ROOT / 'backend' / 'tests'} -q --tb=short"


# ── Test runner ────────────────────────────────────────────────────────────────

def run_tests(cmd: str) -> tuple[bool, str]:
    """Run test command, return (passed, output)."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
        cwd=str(ROOT / "backend"),
    )
    output = result.stdout + result.stderr
    passed = result.returncode == 0
    return passed, output


# ── NEXT_SESSION.md updater ───────────────────────────────────────────────────

def mark_tab_done(text: str, tab_id: str) -> str:
    """
    Set status of tab_id in the status table to '✅ Fertig – verifiziert'.
    Matches rows like: | Tab D | ... | some status |
    """
    pattern = re.compile(
        rf"(\|\s*{re.escape(tab_id)}\s*\|[^|]+\|)\s*([^|]+?)(\s*\|)",
        re.MULTILINE,
    )
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    replacement = rf"\1 ✅ Fertig – verifiziert {ts}\3"
    new_text, n = pattern.subn(replacement, text)
    if n == 0:
        raise ValueError(f"Tab '{tab_id}' not found in NEXT_SESSION.md")
    return new_text


def get_pending_tabs(text: str) -> list[str]:
    """Return tab IDs that are NOT already done."""
    table_re = re.compile(
        r"^\|\s*(Tab[\s\w]+?\d*[\w]*)\s*\|[^|]+\|\s*([^|]+?)\s*\|",
        re.MULTILINE,
    )
    pending = []
    for m in table_re.finditer(text):
        status = m.group(2).strip()
        if not re.search(r"\bOK\b|✅|Fertig", status, re.IGNORECASE):
            pending.append(m.group(1).strip())
    return pending


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Verify tab and update NEXT_SESSION.md")
    parser.add_argument("--tab",      help="Tab ID to verify, e.g. 'Tab D'")
    parser.add_argument("--all",      action="store_true", help="Verify all pending tabs")
    parser.add_argument("--test-cmd", default=DEFAULT_TEST, help="Test command to run")
    parser.add_argument("--next",     default=str(DEFAULT_NEXT))
    parser.add_argument("--dry-run",  action="store_true", help="Don't write changes")
    args = parser.parse_args()

    next_path = Path(args.next)
    text = next_path.read_text(encoding="utf-8")

    if args.all:
        tabs = get_pending_tabs(text)
        if not tabs:
            print("All tabs already done.")
            return
        print(f"Pending tabs: {tabs}")
    elif args.tab:
        tabs = [args.tab]
    else:
        parser.print_help()
        sys.exit(1)

    print(f"Running: {args.test_cmd}")
    passed, output = run_tests(args.test_cmd)
    print(output[-2000:] if len(output) > 2000 else output)

    if not passed:
        print("❌ Tests FAILED – NEXT_SESSION.md not updated.")
        sys.exit(1)

    print(f"✅ Tests passed.")
    for tab_id in tabs:
        try:
            text = mark_tab_done(text, tab_id)
            print(f"  ✓ Marked done: {tab_id}")
        except ValueError as e:
            print(f"  WARNING: {e}")

    if not args.dry_run:
        next_path.write_text(text, encoding="utf-8")
        print(f"  → {next_path} updated.")
    else:
        print("  (dry-run: no file written)")


if __name__ == "__main__":
    main()
