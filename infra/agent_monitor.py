#!/usr/bin/env python3
"""
TokenBroker – Agent Performance Monitor
========================================
Reads SwarmMemory and (optionally) the Supabase `agent_memory` table to
compute per-agent / per-variant success rates, average tokens and latency.

Functions
---------
collect_agent_metrics()   → dict  – aggregated metrics from SwarmMemory JSON
check_agent_health()      → list  – alerts for agents below success threshold
generate_agent_report()   → Path  – writes weekly Markdown to docs/agent_reports/

Schedule (add to monitor.py run_checks or APScheduler):
    from infra.agent_monitor import collect_agent_metrics, check_agent_health
    check_agent_health()   # runs automatically when imported into monitor loop

Env vars (loaded from backend/.env):
    AGENT_SUCCESS_THRESHOLD   (default: 0.70)
    DISCORD_WEBHOOK_URL
    SUPABASE_URL / SUPABASE_ANON_KEY  (optional – for DB-backed agent_memory)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent / "backend" / ".env"
load_dotenv(_env_path)

DISCORD_WEBHOOK_URL    = os.getenv("DISCORD_WEBHOOK_URL", "")
AGENT_SUCCESS_THRESHOLD = float(os.getenv("AGENT_SUCCESS_THRESHOLD", "0.70"))
SUPABASE_URL           = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY      = os.getenv("SUPABASE_ANON_KEY", "")

_REPO_ROOT   = Path(__file__).resolve().parent.parent
_MEMORY_PATH = _REPO_ROOT / "backend" / "agent_swarm" / "memory.json"
_REPORTS_DIR = _REPO_ROOT / "docs" / "agent_reports"


# ── Alerts (mirrors monitor.py pattern) ──────────────────────────────────────

class _AlertLog:
    """Minimal alert sink: Discord + stderr + in-memory list."""

    def __init__(self) -> None:
        self._log: list[dict] = []

    def log_alert(self, level: str, source: str, message: str) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "source": source,
            "message": message,
        }
        self._log.append(entry)
        print(f"[ALERT/{level}] {source}: {message}", file=sys.stderr)
        self._discord(f"{'🔴' if level == 'critical' else '⚠️'} "
                      f"**TokenBroker Agent Alert [{level.upper()}]**\n"
                      f"`{source}` – {message}")

    def recent(self, n: int = 50) -> list[dict]:
        return self._log[-n:]

    def _discord(self, msg: str) -> None:
        if not DISCORD_WEBHOOK_URL:
            return
        try:
            import urllib.request, json as _json
            data = _json.dumps({"content": msg}).encode()
            req = urllib.request.Request(
                DISCORD_WEBHOOK_URL, data=data,
                headers={"Content-Type": "application/json"}, method="POST"
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass


alerts = _AlertLog()


# ── collect_agent_metrics ─────────────────────────────────────────────────────

def collect_agent_metrics(memory_path: Path = _MEMORY_PATH) -> dict[str, Any]:
    """
    Read SwarmMemory JSON and return per-variant and overall agent metrics.

    Returns
    -------
    {
      "total_conversions": int,
      "overall_success_rate": float,
      "avg_tokens": float,
      "avg_latency_s": float,
      "per_variant": {
          variant_id: {
              "calls": int,
              "success_rate": float,
              "avg_tokens": float,
          }
      },
      "top_variants": [ {variant_id, success_rate, calls} ],
      "recent_errors": [ {filename, error, prompt_variant} ],
      "source": "memory_json" | "supabase",
    }
    """
    metrics = _read_memory_json(memory_path)

    # Optionally enrich with Supabase agent_memory table if configured
    if SUPABASE_URL and SUPABASE_ANON_KEY:
        _enrich_from_supabase(metrics)
        metrics["source"] = "supabase"
    else:
        metrics["source"] = "memory_json"

    return metrics


def _read_memory_json(path: Path) -> dict[str, Any]:
    import json

    if not path.exists():
        return _empty_metrics()

    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_metrics()

    convs = state.get("conversions", [])
    variants = state.get("prompt_variants", {})

    total = len(convs)
    successful = [c for c in convs if c.get("score", 0) >= 0.5]
    recent_errors = [
        {
            "filename": c.get("filename", ""),
            "error": c.get("error", ""),
            "prompt_variant": c.get("prompt_variant", ""),
        }
        for c in convs[-200:]
        if c.get("score", 0) < 0.5 and c.get("error")
    ][-10:]

    per_variant: dict[str, dict] = {}
    for vid, v in variants.items():
        calls = v.get("calls", 0)
        per_variant[vid] = {
            "calls": calls,
            "success_rate": round(v.get("successes", 0) / calls, 3) if calls else 0.0,
            "avg_tokens": round(v.get("total_tokens", 0) / calls, 1) if calls else 0.0,
        }

    top_variants = sorted(
        [{"variant": k, **v} for k, v in per_variant.items()],
        key=lambda x: x["success_rate"],
        reverse=True,
    )

    return {
        "total_conversions": total,
        "overall_success_rate": round(len(successful) / total, 3) if total else 0.0,
        "avg_tokens": round(sum(c.get("tokens", 0) for c in convs) / total, 1) if total else 0.0,
        "avg_latency_s": round(sum(c.get("elapsed_s", 0) for c in convs) / total, 3) if total else 0.0,
        "per_variant": per_variant,
        "top_variants": top_variants,
        "recent_errors": recent_errors,
        "runs": len(state.get("run_summaries", [])),
    }


def _enrich_from_supabase(metrics: dict) -> None:
    """Pull additional per-agent rows from `agent_memory` Supabase table."""
    try:
        from supabase import create_client
        client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        rows = (
            client.table("agent_memory")
            .select("agent_id, success, tokens, elapsed_s")
            .limit(1000)
            .execute()
            .data or []
        )
        if not rows:
            return

        by_agent: dict[str, dict] = {}
        for r in rows:
            aid = r.get("agent_id", "unknown")
            if aid not in by_agent:
                by_agent[aid] = {"calls": 0, "successes": 0, "tokens": 0, "elapsed": 0.0}
            by_agent[aid]["calls"] += 1
            by_agent[aid]["successes"] += int(bool(r.get("success")))
            by_agent[aid]["tokens"] += r.get("tokens", 0)
            by_agent[aid]["elapsed"] += r.get("elapsed_s", 0.0)

        metrics["per_agent"] = {
            aid: {
                "calls": d["calls"],
                "success_rate": round(d["successes"] / d["calls"], 3) if d["calls"] else 0.0,
                "avg_tokens": round(d["tokens"] / d["calls"], 1) if d["calls"] else 0.0,
                "avg_latency_s": round(d["elapsed"] / d["calls"], 3) if d["calls"] else 0.0,
            }
            for aid, d in by_agent.items()
        }
    except Exception as exc:
        print(f"[agent_monitor] Supabase enrich failed: {exc}", file=sys.stderr)


def _empty_metrics() -> dict[str, Any]:
    return {
        "total_conversions": 0,
        "overall_success_rate": 0.0,
        "avg_tokens": 0.0,
        "avg_latency_s": 0.0,
        "per_variant": {},
        "top_variants": [],
        "recent_errors": [],
        "runs": 0,
    }


# ── check_agent_health ────────────────────────────────────────────────────────

def check_agent_health(
    threshold: float = AGENT_SUCCESS_THRESHOLD,
    memory_path: Path = _MEMORY_PATH,
) -> list[dict]:
    """
    Check if any prompt variant (agent proxy) is below the success threshold.
    Fires alerts for each underperforming variant.

    Returns list of alert dicts for failing variants.
    """
    metrics = collect_agent_metrics(memory_path)
    triggered: list[dict] = []

    # Overall health check
    overall_rate = metrics["overall_success_rate"]
    total = metrics["total_conversions"]

    if total >= 10 and overall_rate < threshold:
        msg = (
            f"Overall success rate {overall_rate:.0%} is below threshold "
            f"{threshold:.0%} ({total} conversions)"
        )
        alerts.log_alert("critical", "agent_swarm_overall", msg)
        triggered.append({"source": "overall", "rate": overall_rate, "message": msg})

    # Per-variant health checks
    for vid, vstats in metrics["per_variant"].items():
        calls = vstats["calls"]
        rate = vstats["success_rate"]
        if calls >= 5 and rate < threshold:
            msg = (
                f"Variant `{vid}` success rate {rate:.0%} < {threshold:.0%} "
                f"({calls} calls)"
            )
            alerts.log_alert("warning", f"variant:{vid}", msg)
            triggered.append({"source": vid, "rate": rate, "calls": calls, "message": msg})

    if not triggered:
        print(
            f"[agent_monitor] Health OK – overall={overall_rate:.0%} "
            f"({total} conversions, threshold={threshold:.0%})"
        )

    return triggered


# ── generate_agent_report ─────────────────────────────────────────────────────

def generate_agent_report(
    memory_path: Path = _MEMORY_PATH,
    output_dir: Path = _REPORTS_DIR,
) -> Path:
    """
    Generate a weekly Markdown report and write it to docs/agent_reports/.

    Returns the path of the written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics = collect_agent_metrics(memory_path)
    health_alerts = check_agent_health(memory_path=memory_path)

    now = datetime.now(timezone.utc)
    filename = f"agent_report_{now.strftime('%Y-%W')}.md"
    report_path = output_dir / filename

    lines: list[str] = [
        f"# Agent Performance Report – Week {now.strftime('%Y-W%W')}",
        f"Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Total Conversions | {metrics['total_conversions']:,} |",
        f"| Overall Success Rate | {metrics['overall_success_rate']:.1%} |",
        f"| Average Tokens | {metrics['avg_tokens']:.0f} |",
        f"| Average Latency | {metrics['avg_latency_s']:.2f}s |",
        f"| Training Runs | {metrics['runs']} |",
        f"| Data Source | `{metrics.get('source', 'memory_json')}` |",
        "",
        "## Prompt Variant Performance",
        "",
        "| Variant | Calls | Success Rate | Avg Tokens |",
        "|---|---|---|---|",
    ]

    for v in metrics["top_variants"]:
        rate_flag = " ⚠️" if v["success_rate"] < AGENT_SUCCESS_THRESHOLD else ""
        lines.append(
            f"| `{v['variant']}` | {v['calls']} | "
            f"{v['success_rate']:.1%}{rate_flag} | {v['avg_tokens']:.0f} |"
        )

    lines += ["", "## Health Alerts", ""]
    if health_alerts:
        for a in health_alerts:
            lines.append(f"- **{a['source']}**: {a['message']}")
    else:
        lines.append("No alerts – all variants above threshold.")

    if metrics["recent_errors"]:
        lines += [
            "",
            "## Recent Errors (last 10)",
            "",
            "| File | Variant | Error |",
            "|---|---|---|",
        ]
        for e in metrics["recent_errors"]:
            err_short = (e["error"] or "")[:80].replace("|", "\\|")
            lines.append(
                f"| `{e['filename']}` | `{e['prompt_variant']}` | {err_short} |"
            )

    lines += ["", "---", "_Auto-generated by `infra/agent_monitor.py`_"]
    report_path.write_text("\n".join(lines))
    print(f"[agent_monitor] Report written: {report_path}")
    return report_path


# ── Standalone entry point ────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="TokenBroker Agent Monitor")
    parser.add_argument("--report", action="store_true", help="Generate weekly report")
    parser.add_argument("--health", action="store_true", help="Run health check only")
    args = parser.parse_args()

    if args.report:
        path = generate_agent_report()
        print(f"Report: {path}")
    elif args.health:
        triggered = check_agent_health()
        print(f"Alerts: {len(triggered)}")
    else:
        metrics = collect_agent_metrics()
        import json
        print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
