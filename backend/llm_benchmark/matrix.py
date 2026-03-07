"""
Benchmark matrix aggregator.

Takes raw RunResults and produces a provider×category scoring matrix
ranked by a composite score of accuracy, speed, and cost-efficiency.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .runner import BenchmarkRun, RunResult
from .tasks import CATEGORIES


# Cost per 1M tokens (input+output average), USD – mirrors providers.py
_PROVIDER_COST: dict[str, float] = {
    "nvidia":   0.00,   # free tier
    "deepseek": 0.21,   # (0.14 + 0.28) / 2
    "openai":   5.00,   # gpt-4o-mini estimate
    "claude":   3.00,   # claude-haiku estimate
}

# Weights for composite score
WEIGHT_ACCURACY  = 0.40
WEIGHT_SPEED     = 0.30
WEIGHT_COST      = 0.30


@dataclass
class CategoryScore:
    category: str
    accuracy: float         # 0-1
    avg_latency_s: float
    tasks_run: int
    tasks_passed: int


@dataclass
class ProviderScore:
    provider: str
    overall_accuracy: float
    avg_latency_s: float
    cost_per_1m: float
    composite_score: float          # 0-1
    by_category: list[CategoryScore] = field(default_factory=list)
    recommendation: str = ""


@dataclass
class BenchmarkMatrix:
    providers: list[ProviderScore]
    generated_at: str = ""

    def best_for(self, weight: str = "composite") -> Optional[ProviderScore]:
        if not self.providers:
            return None
        key_map = {
            "accuracy":  lambda p: p.overall_accuracy,
            "speed":     lambda p: -p.avg_latency_s,
            "cost":      lambda p: -p.cost_per_1m,
            "composite": lambda p: p.composite_score,
        }
        fn = key_map.get(weight, key_map["composite"])
        return max(self.providers, key=fn)

    def as_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "providers": [
                {
                    "provider":          p.provider,
                    "overall_accuracy":  round(p.overall_accuracy, 3),
                    "avg_latency_s":     round(p.avg_latency_s, 3),
                    "cost_per_1m_usd":   p.cost_per_1m,
                    "composite_score":   round(p.composite_score, 3),
                    "recommendation":    p.recommendation,
                    "by_category": [
                        {
                            "category":    c.category,
                            "accuracy":    round(c.accuracy, 3),
                            "avg_latency": round(c.avg_latency_s, 3),
                            "tasks_run":   c.tasks_run,
                            "tasks_passed": c.tasks_passed,
                        }
                        for c in p.by_category
                    ],
                }
                for p in self.providers
            ],
        }


class MatrixBuilder:
    def build(self, runs: list[BenchmarkRun]) -> BenchmarkMatrix:
        if not runs:
            return BenchmarkMatrix(providers=[])

        # Normalise latency and cost across providers for scoring
        latencies = [r.avg_latency for r in runs if r.avg_latency > 0]
        max_latency = max(latencies) if latencies else 1.0

        all_costs = [_PROVIDER_COST.get(r.provider, 1.0) for r in runs]
        positive_costs = [c for c in all_costs if c > 0]
        max_cost = max(positive_costs) if positive_costs else 1.0

        scored = []
        for run in runs:
            by_cat = self._by_category(run.results)
            acc = run.accuracy
            lat = run.avg_latency

            speed_score = 1.0 - (lat / max_latency) if max_latency > 0 else 1.0
            cost = _PROVIDER_COST.get(run.provider, 1.0)
            cost_score  = 1.0 - (cost / max_cost) if max_cost > 0 else 1.0

            composite = round(
                WEIGHT_ACCURACY * acc
                + WEIGHT_SPEED   * speed_score
                + WEIGHT_COST    * cost_score,
                4,
            )

            scored.append(ProviderScore(
                provider=run.provider,
                overall_accuracy=round(acc, 4),
                avg_latency_s=lat,
                cost_per_1m=cost,
                composite_score=composite,
                by_category=by_cat,
                recommendation=self._recommend(acc, lat, cost),
            ))

        scored.sort(key=lambda p: p.composite_score, reverse=True)

        from datetime import datetime, timezone
        return BenchmarkMatrix(
            providers=scored,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def _by_category(self, results: list[RunResult]) -> list[CategoryScore]:
        cats: dict[str, list[RunResult]] = {}
        for r in results:
            cats.setdefault(r.category, []).append(r)

        out = []
        for cat in CATEGORIES:
            items = cats.get(cat, [])
            if not items:
                continue
            passed = sum(1 for r in items if r.passed)
            latencies = [r.latency_s for r in items if not r.error]
            avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
            out.append(CategoryScore(
                category=cat,
                accuracy=passed / len(items),
                avg_latency_s=round(avg_lat, 3),
                tasks_run=len(items),
                tasks_passed=passed,
            ))
        return out

    @staticmethod
    def _recommend(accuracy: float, latency: float, cost: float) -> str:
        if accuracy >= 0.85 and cost == 0:
            return "Best free-tier option"
        if accuracy >= 0.85 and latency < 3.0:
            return "Best for accuracy + speed"
        if cost == 0:
            return "Free tier – good for low-stakes tasks"
        if accuracy >= 0.80:
            return "Balanced accuracy / cost"
        if latency < 2.0:
            return "Fastest option"
        return "Consider alternatives"
