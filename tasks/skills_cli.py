#!/usr/bin/env python3
"""
TokenBroker Skills CLI
======================
Interaktives Menü und direkter Befehlszugriff auf alle Skills.

Verwendung:
    python tasks/skills_cli.py            # interaktives Menü
    python tasks/skills_cli.py deploy     # direkt ausführen
    python tasks/skills_cli.py test --module payment
    python tasks/skills_cli.py logs --tail 100
    python tasks/skills_cli.py logs --errors-only
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).parent.parent
BACKEND = ROOT / "backend"
SKILLS_DIR = Path(__file__).parent / "skills"
RAILWAY_URL = "https://yondem-production.up.railway.app"

# ── ANSI colours ──────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

ok  = lambda s: f"{GREEN}✓{RESET} {s}"
err = lambda s: f"{RED}✗{RESET} {s}"
inf = lambda s: f"{CYAN}>{RESET} {s}"


def _run(cmd: str, cwd: Path = ROOT, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, shell=True, cwd=cwd,
        capture_output=capture, text=True,
    )


# ── Skills ────────────────────────────────────────────────────────────────────

def skill_deploy(_args: argparse.Namespace) -> int:
    """railway up → health check loop."""
    print(inf("Uploading to Railway..."))
    proc = _run("railway up --service yondem --detach")
    if proc.returncode not in (0, None):
        print(err("railway up failed"))
        return 1

    print(inf("Waiting for health check (max 120s)..."))
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{RAILWAY_URL}/health", timeout=5) as r:
                if r.status == 200:
                    print(ok(f"{RAILWAY_URL}/health → healthy"))
                    return 0
        except Exception:
            pass
        time.sleep(5)
        print("  ...", end="", flush=True)

    print()
    print(err("Health check timed out after 120s"))
    return 1


def skill_context(_args: argparse.Namespace) -> int:
    """Generate and display PROJECT_CONTEXT.md."""
    script = ROOT / "scripts" / "generate_context.py"
    if not script.exists():
        print(err(f"Script not found: {script}"))
        return 1
    print(inf("Generating PROJECT_CONTEXT.md..."))
    proc = _run(f"{sys.executable} {script}")
    if proc.returncode != 0:
        print(err("generate_context.py failed"))
        return 1
    ctx = ROOT / "PROJECT_CONTEXT.md"
    if ctx.exists():
        print(inf(f"Showing {ctx} (press q to quit)..."))
        _run(f"less {ctx}")
    return 0


def skill_techdebt(_args: argparse.Namespace) -> int:
    """Run radon + pylint and write docs/techdebt_report.md."""
    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    report_lines = [f"# Tech Debt Report\nGenerated: {timestamp}\n"]

    # radon cyclomatic complexity
    print(inf("Running radon (cyclomatic complexity)..."))
    cc = _run(f"{sys.executable} -m radon cc {BACKEND}/app/ -s -n C",
              capture=True)
    if cc.returncode == 0:
        report_lines += ["## Cyclomatic Complexity (C+ only)\n```", cc.stdout.strip() or "(none above threshold)", "```\n"]
        if cc.stdout.strip():
            print(cc.stdout.strip())
    else:
        report_lines.append("## Cyclomatic Complexity\n_radon not installed. Run: `pip install radon`_\n")
        print(YELLOW + "  radon not installed – skipping" + RESET)

    # radon maintainability index
    print(inf("Running radon (maintainability index)..."))
    mi = _run(f"{sys.executable} -m radon mi {BACKEND}/app/ -s", capture=True)
    if mi.returncode == 0:
        report_lines += ["## Maintainability Index\n```", mi.stdout.strip() or "(all ok)", "```\n"]
    else:
        report_lines.append("## Maintainability Index\n_radon not installed_\n")

    # pylint
    print(inf("Running pylint..."))
    pl = _run(
        f"{sys.executable} -m pylint {BACKEND}/app/ --disable=all "
        "--enable=R0801,C0303,W0611,C0301 --output-format=text",
        capture=True,
    )
    score_line = next((l for l in (pl.stdout or "").splitlines() if "rated at" in l), "")
    report_lines += [
        "## Pylint (duplicates, unused imports, line length)\n```",
        (pl.stdout.strip() or "pylint not installed") if pl.returncode >= 0 else "pylint not installed",
        "```\n",
    ]
    if score_line:
        print(inf(f"pylint: {score_line.strip()}"))
    elif pl.returncode < 0:
        print(YELLOW + "  pylint not installed – skipping" + RESET)

    # Write report
    out = ROOT / "docs" / "techdebt_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(report_lines), encoding="utf-8")
    print(ok(f"Report saved → {out}"))
    return 0


def skill_test(args: argparse.Namespace) -> int:
    """Run pytest (all or specific module)."""
    module = getattr(args, "module", None)
    if module:
        target = f"{BACKEND}/tests/test_{module}.py"
    else:
        target = f"{BACKEND}/tests/"

    venv_python = BACKEND / "venv" / "bin" / "python"
    py = str(venv_python) if venv_python.exists() else sys.executable

    print(inf(f"Running pytest {target} ..."))
    proc = _run(f"PYTHONPATH={BACKEND} {py} -m pytest {target} -v", cwd=BACKEND)
    if proc.returncode == 0:
        print(ok("All tests passed"))
    else:
        print(err("Some tests failed"))
    return proc.returncode


def skill_logs(args: argparse.Namespace) -> int:
    """Fetch and display Railway logs with error highlighting."""
    tail = getattr(args, "tail", 50)
    errors_only = getattr(args, "errors_only", False)

    print(inf(f"Fetching Railway logs (tail={tail})..."))
    proc = _run(f"railway logs --service yondem --tail {tail}", capture=True)
    if proc.returncode != 0:
        print(err("Failed to fetch logs (railway CLI installed?)"))
        return 1

    error_count = 0
    for line in proc.stdout.splitlines():
        is_error = any(kw in line for kw in ("ERROR", "Exception", "Traceback", "CRITICAL"))
        if errors_only and not is_error:
            continue
        if is_error:
            print(f"{RED}{line}{RESET}")
            error_count += 1
        else:
            print(line)

    label = "error" if error_count == 1 else "errors"
    summary = f"{error_count} {label} found in last {tail} lines"
    print()
    print(ok(summary) if error_count == 0 else err(summary))
    return 0


def skill_status(_args: argparse.Namespace) -> int:
    """Full project status overview."""
    print(f"\n{BOLD}=== TokenBroker Status ==={RESET}\n")

    # Health check
    try:
        with urllib.request.urlopen(f"{RAILWAY_URL}/health", timeout=5) as r:
            health = "ok" if r.status == 200 else f"HTTP {r.status}"
            print(ok(f"Railway: {RAILWAY_URL} → {health}"))
    except Exception as e:
        print(err(f"Railway: {e}"))

    # Git log
    proc = _run("git log --oneline -3", capture=True)
    for line in proc.stdout.strip().splitlines():
        print(f"  Git: {line}")

    # Tests
    venv_python = BACKEND / "venv" / "bin" / "python"
    py = str(venv_python) if venv_python.exists() else sys.executable
    collect = _run(
        f"PYTHONPATH={BACKEND} {py} -m pytest {BACKEND}/tests/ --collect-only -q 2>&1 | tail -2",
        cwd=BACKEND, capture=True,
    )
    summary = collect.stdout.strip().splitlines()
    print(ok(f"Tests: {summary[-1]}") if summary else inf("Tests: (could not collect)"))

    # NEXT_SESSION.md
    ns = ROOT / "NEXT_SESSION.md"
    if not ns.exists():
        ns = Path.home() / "CLAUDE_BRIEFING" / "TokenBroker" / "NEXT_SESSION.md"
    if ns.exists():
        lines = ns.read_text().splitlines()[:5]
        for line in lines:
            if line.strip():
                print(f"  Next: {line.strip()}")
    print()
    return 0


# ── Skill registry ────────────────────────────────────────────────────────────

SKILLS: dict[str, tuple[callable, str]] = {
    "deploy":   (skill_deploy,   "Upload to Railway + health check"),
    "context":  (skill_context,  "Generate + show PROJECT_CONTEXT.md"),
    "techdebt": (skill_techdebt, "Run radon/pylint, write docs/techdebt_report.md"),
    "test":     (skill_test,     "Run pytest (all or --module NAME)"),
    "logs":     (skill_logs,     "Show Railway logs (--tail N, --errors-only)"),
    "status":   (skill_status,   "Full project status overview"),
}


def interactive_menu() -> None:
    """Show numbered skill menu and execute chosen skill."""
    print(f"\n{BOLD}TokenBroker Skills{RESET}")
    print("─" * 30)
    items = list(SKILLS.items())
    for i, (name, (_, desc)) in enumerate(items, 1):
        print(f"  {CYAN}{i}{RESET}. /{name:<12} {desc}")
    print(f"  {CYAN}q{RESET}. quit")
    print()

    choice = input("Select skill: ").strip().lower()
    if choice in ("q", "quit", ""):
        return

    # Accept number or name
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(items):
            name, (fn, _) = items[idx]
        else:
            print(err(f"Invalid selection: {choice}"))
            return
    elif choice.lstrip("/") in SKILLS:
        name = choice.lstrip("/")
        fn, _ = SKILLS[name]
    else:
        print(err(f"Unknown skill: {choice}"))
        return

    print()
    fn(argparse.Namespace())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TokenBroker Skills CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Skills: " + ", ".join(f"/{k}" for k in SKILLS),
    )
    sub = parser.add_subparsers(dest="skill")

    # deploy
    sub.add_parser("deploy", help=SKILLS["deploy"][1])

    # context
    sub.add_parser("context", help=SKILLS["context"][1])

    # techdebt
    sub.add_parser("techdebt", help=SKILLS["techdebt"][1])

    # test
    p_test = sub.add_parser("test", help=SKILLS["test"][1])
    p_test.add_argument("--module", help="Test module name (without test_ prefix)")

    # logs
    p_logs = sub.add_parser("logs", help=SKILLS["logs"][1])
    p_logs.add_argument("--tail", type=int, default=50)
    p_logs.add_argument("--errors-only", action="store_true")

    # status
    sub.add_parser("status", help=SKILLS["status"][1])

    args = parser.parse_args()

    if args.skill is None:
        interactive_menu()
        return

    if args.skill not in SKILLS:
        print(err(f"Unknown skill: {args.skill}"))
        parser.print_help()
        sys.exit(1)

    fn, _ = SKILLS[args.skill]
    sys.exit(fn(args) or 0)


if __name__ == "__main__":
    main()
