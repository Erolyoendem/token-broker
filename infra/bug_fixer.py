#!/usr/bin/env python3
"""
TokenBroker – Automated Bug Fixer
===================================
Überwacht Railway-Logs auf 5xx-Fehler, lässt einen LLM einen Fix generieren
und öffnet automatisch einen Pull-Request auf GitHub.

Run modes:
  python infra/bug_fixer.py            # one-shot (für GitHub Actions / cron)
  python infra/bug_fixer.py --dry-run  # analysiert Fehler, committet nichts

Required env vars:
  RAILWAY_TOKEN        – Railway API-Token (für Log-Abruf)
  TOKENBROKER_API_KEY  – eigener API-Key (LLM-Proxy)
  GH_TOKEN             – GitHub-Token (für PR-Erstellung)

Optional:
  RAILWAY_SERVICE_ID   – Railway Service-ID (default: aus railway.toml)
  TOKENBROKER_URL      – Proxy-URL (default: https://yondem-production.up.railway.app)
  BUG_FIXER_MAX_FIXES  – max. PRs pro Lauf (default: 3)
  DISCORD_WEBHOOK_URL  – für Benachrichtigungen
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────

_env_path = Path(__file__).resolve().parent.parent / "backend" / ".env"
load_dotenv(_env_path)

RAILWAY_TOKEN       = os.getenv("RAILWAY_TOKEN", "")
RAILWAY_SERVICE_ID  = os.getenv("RAILWAY_SERVICE_ID", "")
RAILWAY_PROJECT_ID  = os.getenv("RAILWAY_PROJECT_ID", "")
TOKENBROKER_URL     = os.getenv("TOKENBROKER_URL", "https://yondem-production.up.railway.app")
TOKENBROKER_API_KEY = os.getenv("TOKENBROKER_API_KEY", "")
GH_TOKEN            = os.getenv("GH_TOKEN", os.getenv("GITHUB_TOKEN", ""))
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
MAX_FIXES           = int(os.getenv("BUG_FIXER_MAX_FIXES", "3"))

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ParsedError:
    error_type: str           # e.g. "500 Internal Server Error"
    status_code: int          # 500, 502, 503, …
    url: str                  # e.g. "/chat"
    method: str               # GET, POST, …
    stacktrace: str           # raw traceback lines
    raw_log: str              # full original log chunk
    fingerprint: str = ""     # stable hash for deduplication
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            import hashlib
            key = f"{self.error_type}:{self.url}:{self.stacktrace[:200]}"
            self.fingerprint = hashlib.sha1(key.encode()).hexdigest()[:12]


@dataclass
class GeneratedFix:
    error: ParsedError
    explanation: str          # LLM explanation of the root cause
    patch: str                # unified diff or code block
    files_changed: list[str] = field(default_factory=list)
    pr_url: str = ""
    branch: str = ""


# ── 1. Fetch logs ─────────────────────────────────────────────────────────────

def fetch_recent_errors(lines: int = 100) -> str:
    """
    Fetch the last N log lines from Railway.

    Strategy (tried in order):
      1. Railway CLI  (`railway logs`)  – if CLI is installed and RAILWAY_TOKEN set
      2. Railway API  (GraphQL)         – if RAILWAY_TOKEN + RAILWAY_SERVICE_ID set
      3. Live health probe              – falls back to a minimal synthetic log
    """
    log = _fetch_via_cli(lines)
    if log:
        return log

    log = _fetch_via_api(lines)
    if log:
        return log

    return _fetch_via_health_probe()


def _fetch_via_cli(lines: int) -> str:
    """Use the `railway` CLI if available."""
    if not RAILWAY_TOKEN:
        return ""
    try:
        env = {**os.environ, "RAILWAY_TOKEN": RAILWAY_TOKEN}
        result = subprocess.run(
            ["railway", "logs", "--tail", str(lines)],
            capture_output=True, text=True, timeout=30, env=env,
            cwd=REPO_ROOT,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


def _fetch_via_api(lines: int) -> str:
    """Use the Railway GraphQL API to retrieve deployment logs."""
    if not (RAILWAY_TOKEN and RAILWAY_SERVICE_ID):
        return ""

    query = """
    query GetLogs($serviceId: String!, $limit: Int!) {
      logs(serviceId: $serviceId, limit: $limit) {
        message
        timestamp
        severity
      }
    }
    """
    try:
        r = httpx.post(
            "https://backboard.railway.app/graphql/v2",
            headers={
                "Authorization": f"Bearer {RAILWAY_TOKEN}",
                "Content-Type":  "application/json",
            },
            json={"query": query, "variables": {"serviceId": RAILWAY_SERVICE_ID, "limit": lines}},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        log_entries = data.get("data", {}).get("logs", []) or []
        return "\n".join(
            f"[{e.get('timestamp', '')}] [{e.get('severity', 'INFO')}] {e.get('message', '')}"
            for e in log_entries
        )
    except Exception as exc:
        print(f"[bug_fixer] Railway API error: {exc}", file=sys.stderr)
        return ""


def _fetch_via_health_probe() -> str:
    """
    Probe the live /health endpoint and synthesise a minimal log entry.
    This is the fallback when no Railway credentials are available.
    """
    print("[bug_fixer] No Railway credentials – probing health endpoint as fallback")
    try:
        r = httpx.get(f"{TOKENBROKER_URL}/health", timeout=10, follow_redirects=True)
        ts = datetime.now(timezone.utc).isoformat()
        if r.status_code >= 500:
            return (
                f"[{ts}] [ERROR] GET /health HTTP 500\n"
                f"[{ts}] [ERROR] Internal Server Error – health check failed\n"
                f"[{ts}] [ERROR] Traceback (most recent call last):\n"
                f"[{ts}] [ERROR]   File 'app/main.py', line 61, in health_check\n"
                f"[{ts}] [ERROR] RuntimeError: Service unhealthy\n"
            )
        return f"[{ts}] [INFO] GET /health HTTP {r.status_code} – OK (no errors found)\n"
    except Exception as exc:
        ts = datetime.now(timezone.utc).isoformat()
        return (
            f"[{ts}] [ERROR] GET /health connection failed: {exc}\n"
            f"[{ts}] [ERROR] HTTPConnectError – service may be down\n"
        )


# ── 2. Parse errors ───────────────────────────────────────────────────────────

# Patterns for log lines that signal an HTTP 5xx response
# Matches: "HTTP/1.1 500", "HTTP 500", "500 Internal Server Error", "500 Bad Gateway", etc.
_5XX_PATTERN    = re.compile(r"HTTP[/ ]\S*\s+(?P<code>5\d{2})|(?P<code2>5\d{2})(?:\s+\w[\w ]*?)?")
_ROUTE_PATTERN  = re.compile(r'"(?P<method>GET|POST|PUT|DELETE|PATCH)\s+(?P<url>/[^\s"]*)"')
_TB_START       = re.compile(r"Traceback \(most recent call last\)")
_TIMESTAMP_PAT  = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def parse_errors(log: str) -> list[ParsedError]:
    """
    Scan log text and return one ParsedError per distinct 5xx event.
    Groups consecutive lines into error chunks, deduplicates by fingerprint.
    """
    lines = log.splitlines()
    errors: list[ParsedError] = []
    seen_fingerprints: set[str] = set()
    i = 0

    while i < len(lines):
        line = lines[i]

        # Look for a 5xx status code on this line
        m5 = _5XX_PATTERN.search(line)
        if not m5:
            i += 1
            continue

        status_code = int(m5.group("code") or m5.group("code2"))

        # Collect up to 40 surrounding lines as context
        chunk_start = max(0, i - 5)
        chunk_end   = min(len(lines), i + 35)
        chunk       = "\n".join(lines[chunk_start:chunk_end])

        # Extract route: prefer the 5xx line itself, then ±3 lines
        local_start = max(0, i - 2)
        local_end   = min(len(lines), i + 3)
        local_ctx   = "\n".join(lines[local_start:local_end])
        route_m = _ROUTE_PATTERN.search(local_ctx) or _ROUTE_PATTERN.search(chunk)
        method  = route_m.group("method") if route_m else "UNKNOWN"
        url     = route_m.group("url")    if route_m else "/unknown"

        # Extract traceback
        tb_lines: list[str] = []
        in_tb = False
        for cl in lines[chunk_start:chunk_end]:
            if _TB_START.search(cl):
                in_tb = True
            if in_tb:
                tb_lines.append(cl)
                # Stop at the final exception line (no leading whitespace after traceback)
                if tb_lines and len(tb_lines) > 2 and not cl.startswith(" ") and not _TB_START.search(cl):
                    break
        stacktrace = "\n".join(tb_lines) if tb_lines else line

        # Timestamp
        ts_m  = _TIMESTAMP_PAT.search(line)
        ts    = ts_m.group(0) if ts_m else ""

        error = ParsedError(
            error_type  = f"HTTP {status_code}",
            status_code = status_code,
            url         = url,
            method      = method,
            stacktrace  = stacktrace,
            raw_log     = chunk,
            timestamp   = ts,
        )

        if error.fingerprint not in seen_fingerprints:
            seen_fingerprints.add(error.fingerprint)
            errors.append(error)

        i += 1  # advance one line; fingerprint deduplication handles repeats

    return errors


# backward-compat alias used in tests / workflow
def parse_error(log: str) -> list[ParsedError]:
    return parse_errors(log)


# ── 3. Generate fix ───────────────────────────────────────────────────────────

_SYSTEM_PROMPT = textwrap.dedent("""\
    You are a senior Python/FastAPI developer reviewing a production error in the
    TokenBroker API (FastAPI + Supabase + Railway).

    When given an error, respond with ONLY a JSON object with these keys:
      "explanation": one-paragraph root-cause analysis
      "patch": a unified diff (--- a/file ... +++ b/file) or clearly labelled
               code block fixing the issue
      "files_changed": list of file paths affected
      "confidence": "high" | "medium" | "low"

    Keep the patch minimal and safe. Do not remove error handling.
""")


def generate_fix(error: ParsedError) -> GeneratedFix | None:
    """
    Call the TokenBroker LLM proxy to generate a fix for the given error.
    Returns None if the LLM is unavailable or confidence is too low.
    """
    if not TOKENBROKER_API_KEY:
        print("[bug_fixer] TOKENBROKER_API_KEY not set – skipping LLM fix generation")
        return None

    user_message = textwrap.dedent(f"""\
        Production error detected in TokenBroker API:

        Status: {error.status_code} on {error.method} {error.url}
        Timestamp: {error.timestamp}

        Stacktrace / Log context:
        ```
        {error.stacktrace[:2000]}
        ```

        Full log chunk:
        ```
        {error.raw_log[:1500]}
        ```

        Generate a minimal, safe fix. Respond with JSON only.
    """)

    try:
        r = httpx.post(
            f"{TOKENBROKER_URL}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {TOKENBROKER_API_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
            },
            timeout=60,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        print(f"[bug_fixer] LLM request failed: {exc}", file=sys.stderr)
        return None

    # Parse JSON from LLM response (may be wrapped in a markdown code block)
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    raw_json   = json_match.group(1) if json_match else content

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        # Fallback: extract any JSON-like object
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            print("[bug_fixer] Could not parse LLM JSON response", file=sys.stderr)
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    confidence = data.get("confidence", "low")
    if confidence == "low":
        print(f"[bug_fixer] LLM confidence=low for {error.fingerprint} – skipping")
        return None

    return GeneratedFix(
        error       = error,
        explanation = data.get("explanation", ""),
        patch       = data.get("patch", ""),
        files_changed = data.get("files_changed", []),
    )


# ── 4. Apply fix (branch + commit + PR) ──────────────────────────────────────

def apply_fix(fix: GeneratedFix, dry_run: bool = False) -> str | None:
    """
    1. Create a new branch `fix/5xx-<fingerprint>`
    2. Write the patch / explanation to a markdown file for human review
    3. Commit and push
    4. Open a GitHub Pull-Request via `gh`
    Returns the PR URL or None on failure.
    """
    branch = f"fix/5xx-{fix.error.fingerprint}-{int(time.time())}"
    fix.branch = branch

    if dry_run:
        print(f"[bug_fixer] [DRY RUN] Would create branch {branch} and open PR")
        print(f"[bug_fixer] Explanation: {fix.explanation[:200]}")
        return None

    try:
        # Ensure we're on main and up-to-date
        _git(["checkout", "main"])
        _git(["pull", "--ff-only"])

        # Create branch
        _git(["checkout", "-b", branch])

        # Write a human-readable fix proposal file
        proposal_path = REPO_ROOT / "docs" / "fix_proposals" / f"{branch}.md"
        proposal_path.parent.mkdir(parents=True, exist_ok=True)
        proposal_path.write_text(_render_proposal(fix))

        # Stage and commit
        _git(["add", str(proposal_path)])
        _git([
            "commit", "-m",
            f"[bug_fixer] Auto-fix proposal for {fix.error.status_code} on {fix.error.url}\n\n"
            f"Error fingerprint: {fix.error.fingerprint}\n"
            f"Confidence: {fix.explanation[:80]}",
        ])

        # Push
        _git(["push", "origin", branch])

        # Create PR
        pr_body = _render_pr_body(fix)
        result = subprocess.run(
            [
                "gh", "pr", "create",
                "--title",  f"[auto-fix] {fix.error.status_code} on {fix.error.url} ({fix.error.fingerprint})",
                "--body",   pr_body,
                "--base",   "main",
                "--head",   branch,
                "--label",  "auto-fix",
            ],
            capture_output=True, text=True, timeout=30,
            cwd=REPO_ROOT,
            env={**os.environ, "GH_TOKEN": GH_TOKEN},
        )
        if result.returncode != 0:
            print(f"[bug_fixer] gh pr create failed: {result.stderr}", file=sys.stderr)
            _git(["checkout", "main"])
            return None

        pr_url = result.stdout.strip()
        fix.pr_url = pr_url

        # Return to main
        _git(["checkout", "main"])
        return pr_url

    except Exception as exc:
        print(f"[bug_fixer] apply_fix error: {exc}", file=sys.stderr)
        try:
            _git(["checkout", "main"])
        except Exception:
            pass
        return None


def _git(args: list[str]) -> str:
    result = subprocess.run(
        ["git"] + args,
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout.strip()


def _render_proposal(fix: GeneratedFix) -> str:
    return textwrap.dedent(f"""\
        # Auto-Fix Proposal

        **Error:** `{fix.error.status_code}` on `{fix.error.method} {fix.error.url}`
        **Fingerprint:** `{fix.error.fingerprint}`
        **Detected at:** {fix.error.timestamp}
        **Branch:** `{fix.branch}`

        ## Root Cause

        {fix.explanation}

        ## Proposed Patch

        ```diff
        {fix.patch}
        ```

        ## Files Changed

        {chr(10).join(f"- `{f}`" for f in fix.files_changed) or "_(see patch above)_"}

        ---
        _Generated by `infra/bug_fixer.py`. Review carefully before merging._
    """)


def _render_pr_body(fix: GeneratedFix) -> str:
    return textwrap.dedent(f"""\
        ## Automated Bug Fix Proposal

        This PR was generated automatically by `infra/bug_fixer.py`.

        | Field | Value |
        |-------|-------|
        | Status | `{fix.error.status_code}` |
        | Endpoint | `{fix.error.method} {fix.error.url}` |
        | Fingerprint | `{fix.error.fingerprint}` |
        | Detected | {fix.error.timestamp} |

        ## Root Cause Analysis

        {fix.explanation}

        ## Proposed Fix

        ```diff
        {fix.patch[:3000]}
        ```

        ## Review Checklist

        - [ ] Root cause analysis looks correct
        - [ ] Patch is safe (no removed error handling, no regression risk)
        - [ ] Tests still pass after applying this change
        - [ ] Manual test on staging before merging

        ---
        > ⚠️ AI-generated fix – human review required before merging.
    """)


# ── Discord notification ──────────────────────────────────────────────────────

def _notify(message: str) -> None:
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        httpx.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10).raise_for_status()
    except Exception:
        pass


# ── Main ──────────────────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*55}\n[bug_fixer] {ts}\n{'='*55}")

    # 1. Fetch
    log = fetch_recent_errors(lines=100)
    print(f"[bug_fixer] Fetched {len(log.splitlines())} log lines")

    # 2. Parse
    errors = parse_errors(log)
    print(f"[bug_fixer] Found {len(errors)} unique 5xx error(s)")

    if not errors:
        print("[bug_fixer] No 5xx errors – nothing to do")
        return {"errors": 0, "fixes_attempted": 0, "prs_opened": 0}

    _notify(
        f"🔴 **TokenBroker Bug Fixer** – {len(errors)} error(s) detected\n"
        + "\n".join(f"  • `{e.status_code}` on `{e.method} {e.url}`" for e in errors[:5])
    )

    # 3+4. Generate & apply (up to MAX_FIXES)
    prs: list[str] = []
    for error in errors[:MAX_FIXES]:
        print(f"\n[bug_fixer] Processing {error.fingerprint}: {error.status_code} {error.url}")
        fix = generate_fix(error)
        if fix is None:
            print(f"[bug_fixer] No fix generated for {error.fingerprint}")
            continue
        pr_url = apply_fix(fix, dry_run=dry_run)
        if pr_url:
            prs.append(pr_url)
            _notify(
                f"🔧 **Auto-Fix PR opened**\n"
                f"Error: `{error.status_code}` on `{error.method} {error.url}`\n"
                f"PR: {pr_url}"
            )
            print(f"[bug_fixer] PR opened: {pr_url}")

    result = {
        "errors": len(errors),
        "fixes_attempted": min(len(errors), MAX_FIXES),
        "prs_opened": len(prs),
        "pr_urls": prs,
    }
    print(f"\n[bug_fixer] Summary: {result}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="TokenBroker automated bug fixer")
    parser.add_argument("--dry-run", action="store_true",
                        help="Analyse errors but do not create branches or PRs")
    parser.add_argument("--lines", type=int, default=100,
                        help="Number of log lines to fetch (default 100)")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
