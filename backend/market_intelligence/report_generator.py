"""Generates weekly market intelligence reports as Markdown files."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path

REPORTS_DIR = Path(__file__).parent.parent.parent / "docs" / "market_reports"
STRATEGY_DIR = Path(__file__).parent.parent.parent / "docs" / "strategy"


class ReportGenerator:
    def __init__(self, reports_dir: Path = REPORTS_DIR, strategy_dir: Path = STRATEGY_DIR):
        self.reports_dir = reports_dir
        self.strategy_dir = strategy_dir
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.strategy_dir.mkdir(parents=True, exist_ok=True)

    def generate_weekly_report(
        self,
        competitor_data: list[dict],
        trend_data: dict,
        opportunity_data: dict,
    ) -> Path:
        now = datetime.now(timezone.utc)
        filename = self.reports_dir / f"market_report_{now.strftime('%Y-%m-%d')}.md"

        lines = [
            f"# TokenBroker – Market Intelligence Report",
            f"Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "## Competitor Activity",
            "",
        ]

        for c in competitor_data:
            stats = c.get("stats", {})
            release = c.get("latest_release", {})
            lines.append(f"### {c['name']}")
            if stats.get("error"):
                lines.append(f"- Error: {stats['error']}")
            else:
                lines.append(f"- Stars: {stats.get('stars', 'n/a')} | Forks: {stats.get('forks', 'n/a')}")
                lines.append(f"- Last push: {stats.get('last_push', 'n/a')[:10]}")
            if release.get("tag") and not release.get("error"):
                lines.append(f"- Latest release: [{release['tag']}]({release['url']}) ({release.get('published_at', '')[:10]})")
            lines.append("")

        lines += [
            "## AI Research Trends (arXiv)",
            "",
            f"Search terms analyzed: {', '.join(trend_data.get('terms', []))}",
            f"Total papers found: {trend_data.get('total_papers', 0)}",
            "",
        ]

        for term, papers in trend_data.get("papers", {}).items():
            lines.append(f"**{term}**")
            for p in papers[:2]:
                if "error" not in p:
                    lines.append(f"- [{p['title']}]({p['url']})")
            lines.append("")

        lines += [
            "## Opportunities & Gaps",
            "",
            "### Unique TokenBroker Advantages",
        ]
        for adv in opportunity_data.get("unique_advantages", []):
            lines.append(f"- {adv.replace('_', ' ')}")

        lines += ["", "### Top Recommendations"]
        for rec in opportunity_data.get("top_recommendations", []):
            lines.append(f"- **{rec['feature'].replace('_', ' ')}** (priority: {rec['priority']}) – {rec['suggestion']}")

        lines.append("")
        report_text = "\n".join(lines)
        filename.write_text(report_text, encoding="utf-8")
        return filename

    def generate_strategy_suggestions(self, opportunity_data: dict) -> Path:
        now = datetime.now(timezone.utc)
        filename = self.strategy_dir / f"strategy_{now.strftime('%Y-%m-%d')}.md"

        lines = [
            "# TokenBroker – Strategy Suggestions",
            f"Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "## Auto-Generated Tab Prompts (based on market gaps)",
            "",
        ]

        tab_num = 20
        for rec in opportunity_data.get("top_recommendations", []):
            feature = rec["feature"].replace("_", " ").title()
            adopters = ", ".join(rec["adopted_by"])
            lines += [
                f"### Tab {tab_num} – {feature}",
                f"Priority: {rec['priority']}/10 | Already offered by: {adopters}",
                "",
                f"```",
                f"Du bist Entwickler im TokenBroker-Projekt. Implementiere {feature}.",
                f"Orientiere dich an den Implementierungen von {adopters}.",
                f"1. Analysiere, wie {adopters} {feature} implementiert haben.",
                f"2. Entwirf eine TokenBroker-spezifische Lösung.",
                f"3. Implementiere, teste, committe und deploye.",
                f"```",
                "",
            ]
            tab_num += 1

        filename.write_text("\n".join(lines), encoding="utf-8")
        return filename
