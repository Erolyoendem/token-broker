#!/usr/bin/env python3
"""
TokenBroker – Health & Usage Monitor
=====================================
Run modes:
  python infra/monitor.py            # one-shot (for GitHub Actions / cron)
  python infra/monitor.py --loop     # continuous, checks every hour (APScheduler)

Required env vars (also loaded from backend/.env):
  DISCORD_WEBHOOK_URL
  SUPABASE_URL
  SUPABASE_ANON_KEY

Optional:
  HEALTH_URL              (default: https://yondem-production.up.railway.app/health)
  ALERT_TOKEN_THRESHOLD   (default: 500000  – tokens/24h before alerting)
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from supabase import create_client

# ── Load .env from backend/ if running from repo root ───────────────────────
_env_path = Path(__file__).resolve().parent.parent / "backend" / ".env"
load_dotenv(_env_path)

DISCORD_WEBHOOK_URL  = os.getenv("DISCORD_WEBHOOK_URL", "")
SUPABASE_URL         = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY    = os.getenv("SUPABASE_ANON_KEY", "")
HEALTH_URL           = os.getenv("HEALTH_URL", "https://yondem-production.up.railway.app/health")
ALERT_TOKEN_THRESHOLD = int(os.getenv("ALERT_TOKEN_THRESHOLD", "500000"))


# ── Discord ──────────────────────────────────────────────────────────────────

def notify(message: str) -> None:
    if not DISCORD_WEBHOOK_URL:
        print(f"[discord] no webhook configured – would send: {message}")
        return
    try:
        r = httpx.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
        r.raise_for_status()
    except Exception as exc:
        print(f"[discord] send failed: {exc}", file=sys.stderr)


# ── Health check ─────────────────────────────────────────────────────────────

def check_health() -> bool:
    """GET /health – returns True if service is up and reports status=ok."""
    try:
        r = httpx.get(HEALTH_URL, timeout=10, follow_redirects=True)
        if r.status_code != 200:
            notify(
                f"🔴 **TokenBroker Health FAIL**\n"
                f"URL: `{HEALTH_URL}`\n"
                f"HTTP {r.status_code} – {r.text[:200]}"
            )
            print(f"[health] FAIL  HTTP {r.status_code}")
            return False
        data = r.json()
        if data.get("status") != "ok":
            notify(
                f"⚠️ **TokenBroker Health WARNING**\n"
                f"URL: `{HEALTH_URL}`\n"
                f"Unexpected response: `{data}`"
            )
            print(f"[health] WARN  unexpected body: {data}")
            return False
        print(f"[health] OK    {data}")
        return True
    except Exception as exc:
        notify(
            f"🔴 **TokenBroker Health ERROR**\n"
            f"URL: `{HEALTH_URL}`\n"
            f"Exception: `{exc}`"
        )
        print(f"[health] ERROR {exc}", file=sys.stderr)
        return False


# ── Token-usage check ────────────────────────────────────────────────────────

def check_token_usage() -> dict:
    """
    Query token_usage for the last 24 h.
    Returns a summary dict; sends Discord alert if threshold exceeded.
    """
    if not (SUPABASE_URL and SUPABASE_ANON_KEY):
        print("[usage] Supabase env vars missing – skipping usage check")
        return {}

    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    try:
        result = (
            client.table("token_usage")
            .select("tokens_used, provider, user_id")
            .gte("timestamp", since)
            .execute()
        )
    except Exception as exc:
        notify(f"⚠️ **TokenBroker Monitor** – Supabase query failed: `{exc}`")
        print(f"[usage] Supabase error: {exc}", file=sys.stderr)
        return {}

    rows = result.data or []
    total_tokens = sum(r["tokens_used"] for r in rows)

    # Per-provider breakdown
    by_provider: dict[str, int] = {}
    for r in rows:
        by_provider[r["provider"]] = by_provider.get(r["provider"], 0) + r["tokens_used"]

    # Per-user breakdown (top 5)
    by_user: dict[str, int] = {}
    for r in rows:
        uid = r["user_id"]
        by_user[uid] = by_user.get(uid, 0) + r["tokens_used"]
    top_users = sorted(by_user.items(), key=lambda x: x[1], reverse=True)[:5]

    summary = {
        "period_hours": 24,
        "total_tokens": total_tokens,
        "by_provider": by_provider,
        "top_users": top_users,
        "row_count": len(rows),
    }
    print(f"[usage] 24h total={total_tokens}  rows={len(rows)}  by_provider={by_provider}")

    if total_tokens >= ALERT_TOKEN_THRESHOLD:
        provider_lines = "\n".join(
            f"  • `{p}`: {t:,}" for p, t in sorted(by_provider.items(), key=lambda x: x[1], reverse=True)
        )
        user_lines = "\n".join(f"  • `{u[:8]}…`: {t:,}" for u, t in top_users)
        notify(
            f"⚠️ **TokenBroker – High Token Usage Alert**\n"
            f"Last 24 h: **{total_tokens:,}** tokens (threshold: {ALERT_TOKEN_THRESHOLD:,})\n\n"
            f"**By provider:**\n{provider_lines}\n\n"
            f"**Top users:**\n{user_lines}"
        )

    return summary


# ── Main ─────────────────────────────────────────────────────────────────────

def run_checks() -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*50}\n[monitor] {ts}\n{'='*50}")
    check_health()
    check_token_usage()


def main() -> None:
    parser = argparse.ArgumentParser(description="TokenBroker monitor")
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously every hour using APScheduler",
    )
    args = parser.parse_args()

    if args.loop:
        try:
            from apscheduler.schedulers.blocking import BlockingScheduler
        except ImportError:
            print("APScheduler not installed. Run: pip install APScheduler", file=sys.stderr)
            sys.exit(1)

        scheduler = BlockingScheduler()
        # Run immediately on start, then every hour
        run_checks()
        scheduler.add_job(run_checks, "interval", hours=1)
        print("[monitor] Scheduler started – running every hour. Ctrl+C to stop.")
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            print("[monitor] Stopped.")
    else:
        run_checks()


if __name__ == "__main__":
    main()
