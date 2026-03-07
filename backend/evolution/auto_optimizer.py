"""
AutoOptimizer – Thompson Sampling for provider/model selection.

Thompson Sampling is a Bayesian bandit algorithm:
  - Each provider has a Beta(alpha, beta) distribution where
    alpha = successes + 1, beta = failures + 1
  - At decision time, sample once from each distribution and pick the argmax
  - This naturally balances exploration (uncertain providers) and exploitation
    (proven performers), with no external dependencies.

Usage
-----
    opt = AutoOptimizer(metrics_collector)

    # At routing time:
    best = opt.select_provider(
        candidates=["nvidia", "deepseek"],
        task_type="ruby_to_python",
    )

    # Force re-evaluation of thresholds:
    alerts = opt.check_thresholds(success_rate_floor=0.6, latency_ceil_s=5.0)
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from evolution.metrics_collector import MetricsCollector

# Default threshold configuration (can be overridden per call)
DEFAULT_SUCCESS_RATE_FLOOR = 0.6   # alert if success rate drops below 60%
DEFAULT_LATENCY_CEIL_S     = 10.0  # alert if avg latency exceeds 10 s


class AutoOptimizer:
    def __init__(self, collector: "MetricsCollector") -> None:
        self._col = collector

    # ── Provider selection ─────────────────────────────────────────────────────

    def select_provider(
        self,
        candidates: list[str],
        task_type: str = "",
        *,
        seed: int | None = None,
    ) -> str:
        """
        Return the best provider from *candidates* using Thompson Sampling.

        If no history exists for a candidate, it is treated as a fresh arm
        with Beta(1, 1) = uniform – encouraging exploration.
        """
        if not candidates:
            raise ValueError("candidates must not be empty")

        rng = random.Random(seed)

        best_provider = candidates[0]
        best_sample   = -1.0

        for provider in candidates:
            hist = self._col.provider_history(provider, task_type)
            alpha = hist["successes"] + 1
            beta  = hist["failures"]  + 1
            sample = rng.betavariate(alpha, beta)
            if sample > best_sample:
                best_sample   = sample
                best_provider = provider

        return best_provider

    def provider_scores(
        self,
        candidates: list[str],
        task_type: str = "",
    ) -> list[dict[str, Any]]:
        """Return sorted list of providers with their historical stats."""
        results = []
        for provider in candidates:
            hist = self._col.provider_history(provider, task_type)
            total = hist["successes"] + hist["failures"]
            success_rate = hist["successes"] / total if total else None
            results.append({
                "provider":     provider,
                "calls":        total,
                "successes":    hist["successes"],
                "failures":     hist["failures"],
                "success_rate": round(success_rate, 3) if success_rate is not None else None,
                "alpha":        hist["successes"] + 1,
                "beta":         hist["failures"] + 1,
            })
        return sorted(results, key=lambda r: r["success_rate"] or 0.0, reverse=True)

    # ── Threshold monitoring ───────────────────────────────────────────────────

    def check_thresholds(
        self,
        success_rate_floor: float = DEFAULT_SUCCESS_RATE_FLOOR,
        latency_ceil_s: float     = DEFAULT_LATENCY_CEIL_S,
        last_hours: int           = 24,
    ) -> list[dict[str, Any]]:
        """
        Check all providers against configured thresholds.

        Returns a list of alert dicts (empty = everything OK).
        """
        stats = self._col.get_stats(last_hours=last_hours)
        alerts: list[dict[str, Any]] = []

        for row in stats:
            provider = row["provider"]
            success_rate = (row["success_rate_pct"] or 0) / 100
            avg_latency  = row["avg_latency_s"] or 0.0

            if success_rate < success_rate_floor:
                alerts.append({
                    "provider":   provider,
                    "type":       "low_success_rate",
                    "value":      round(success_rate, 3),
                    "threshold":  success_rate_floor,
                    "action":     f"Consider routing away from {provider}",
                })

            if avg_latency > latency_ceil_s:
                alerts.append({
                    "provider":   provider,
                    "type":       "high_latency",
                    "value":      avg_latency,
                    "threshold":  latency_ceil_s,
                    "action":     f"Latency spike detected on {provider}",
                })

        return alerts

    # ── Lessons learned ────────────────────────────────────────────────────────

    def lessons_learned(
        self,
        task_type: str = "",
        last_hours: int = 168,   # 7 days
    ) -> list[str]:
        """
        Generate human-readable best-practice lines from historical data.
        """
        stats = self._col.get_stats(last_hours=last_hours)
        if not stats:
            return ["No data yet – run some agent tasks to generate insights."]

        lines: list[str] = []
        top = max(stats, key=lambda r: r["success_rate_pct"] or 0)
        worst = min(stats, key=lambda r: r["success_rate_pct"] or 0)

        lines.append(
            f"Best provider: {top['provider']} "
            f"({top['success_rate_pct']}% success over {top['calls']} calls)"
        )
        if top["provider"] != worst["provider"]:
            lines.append(
                f"Worst provider: {worst['provider']} "
                f"({worst['success_rate_pct']}% success over {worst['calls']} calls)"
            )

        fastest = min(stats, key=lambda r: r["avg_latency_s"] or 9999)
        lines.append(
            f"Fastest provider: {fastest['provider']} "
            f"(avg {fastest['avg_latency_s']}s latency)"
        )

        most_efficient = max(stats, key=lambda r: (r["success_rate_pct"] or 0) / max(r["avg_latency_s"] or 1, 0.001))
        lines.append(
            f"Most cost-efficient: {most_efficient['provider']} "
            f"(best success-rate/latency ratio)"
        )

        return lines
