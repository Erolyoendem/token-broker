"""
ReportGenerator – LLM-gestuetzter Big-4-Stil Bericht.

Erstellt einen Bericht in docs/assessment/ mit:
  - Executive Summary
  - Detailanalyse (Code, Abhaengigkeiten, Tech Debt)
  - Priorisierte Handlungsempfehlungen

Der Narrative-Text wird via TokenBroker-Proxy (LLM) generiert.
Faellt der Proxy aus, wird ein strukturierter Fallback-Bericht erstellt.
"""
from __future__ import annotations

import os
import json
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from .code_scanner import ScanResult
from .dependency_analyzer import AssessmentGraph
from .tech_debt_estimator import TechDebtResult

load_dotenv()

_PROXY_URL = os.getenv(
    "TOKENBROKER_PROXY_URL",
    "https://yondem-production.up.railway.app/v1/chat/completions",
)
_API_KEY   = os.getenv("TOKENBROKER_KEY", "")
_DOCS_DIR  = Path(__file__).parent.parent.parent / "docs" / "assessment"

_GRADE_DESC = {
    "A": "Hervorragend – minimale technische Schulden",
    "B": "Gut – kleine Verbesserungen empfehlenswert",
    "C": "Akzeptabel – moderater Handlungsbedarf",
    "D": "Kritisch – dringender Refactoring-Bedarf",
    "F": "Notfall – sofortiger Handlungsbedarf",
}


class ReportGenerator:
    """Erstellt einen Big-4-Stil Assessment-Bericht als Markdown."""

    def __init__(self, output_dir: str | Path = _DOCS_DIR) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        project_name: str,
        scan: ScanResult,
        dep_graph: AssessmentGraph,
        debt: TechDebtResult,
        repo_url: str = "",
    ) -> Path:
        """
        Erstellt vollstaendigen Bericht und speichert ihn als Markdown.

        Returns
        -------
        Path – Pfad zur generierten Report-Datei
        """
        narrative = self._generate_narrative(project_name, scan, dep_graph, debt)
        report = self._compose_report(
            project_name, scan, dep_graph, debt, narrative, repo_url
        )
        slug = re.sub(r"[^\w-]", "_", project_name.lower())[:40]
        ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        path = self.output_dir / f"{slug}_{ts}.md"
        path.write_text(report, encoding="utf-8")
        return path

    # ── LLM narrative ──────────────────────────────────────────────────────────

    def _generate_narrative(
        self,
        project_name: str,
        scan: ScanResult,
        dep_graph: AssessmentGraph,
        debt: TechDebtResult,
    ) -> dict[str, str]:
        """Generiert Executive Summary und Empfehlungen via LLM."""
        context = self._build_llm_context(project_name, scan, dep_graph, debt)

        system = (
            "Du bist ein erfahrener IT-Berater (Big-4-Niveau). "
            "Erstelle praegnante, professionelle Texte fuer einen technischen Assessment-Bericht. "
            "Schreibe auf Deutsch. Sei konkret und handlungsorientiert."
        )

        prompts = {
            "executive_summary": (
                f"Schreibe ein Executive Summary (max. 150 Woerter) fuer das Projekt '{project_name}'.\n"
                f"Kontext: {context}"
            ),
            "recommendations": (
                f"Formuliere 5 priorisierte Handlungsempfehlungen fuer '{project_name}'.\n"
                f"Format: nummerierte Liste, jeweils: Empfehlung | Aufwand (S/M/L) | Impact (Hoch/Mittel/Niedrig)\n"
                f"Kontext: {context}"
            ),
        }

        results: dict[str, str] = {}
        for key, prompt in prompts.items():
            results[key] = self._call_llm(system, prompt)

        return results

    def _call_llm(self, system: str, user: str) -> str:
        if not _API_KEY:
            return self._fallback_text(user)
        try:
            resp = httpx.post(
                _PROXY_URL,
                json={
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ]
                },
                headers={"Authorization": f"Bearer {_API_KEY}"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception:
            return self._fallback_text(user)

    @staticmethod
    def _fallback_text(prompt: str) -> str:
        if "Executive Summary" in prompt or "executive_summary" in prompt:
            return (
                "Das Projekt wurde einer automatisierten Analyse unterzogen. "
                "Die Ergebnisse zeigen den aktuellen technischen Zustand "
                "und priorisierte Handlungsempfehlungen."
            )
        return (
            "1. Technische Schulden reduzieren | M | Hoch\n"
            "2. Testabdeckung erhoehen | M | Hoch\n"
            "3. Grosse Dateien refaktorieren | S | Mittel\n"
            "4. Abhaengigkeiten aktualisieren | S | Hoch\n"
            "5. Dokumentation vervollstaendigen | S | Mittel"
        )

    def _build_llm_context(
        self,
        project_name: str,
        scan: ScanResult,
        dep_graph: AssessmentGraph,
        debt: TechDebtResult,
    ) -> str:
        top_lang = list(scan.lines_by_language.keys())[:3]
        pain_summary = "; ".join(
            f"{p.category}({p.severity})" for p in dep_graph.pain_points[:5]
        )
        return (
            f"Projekt: {project_name} | "
            f"Dateien: {scan.total_files} | "
            f"LOC: {scan.total_lines:,} | "
            f"Sprachen: {', '.join(top_lang)} | "
            f"Frameworks: {', '.join(scan.frameworks_detected) or 'keine erkannt'} | "
            f"Tech-Debt-Score: {debt.total_score}/100 (Note: {debt.grade}) | "
            f"Pain Points: {pain_summary or 'keine kritischen'}"
        )

    # ── Report composition ─────────────────────────────────────────────────────

    def _compose_report(
        self,
        project_name: str,
        scan: ScanResult,
        dep_graph: AssessmentGraph,
        debt: TechDebtResult,
        narrative: dict[str, str],
        repo_url: str,
    ) -> str:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        grade_desc = _GRADE_DESC.get(debt.grade, "")

        # Pain points tabelle
        pain_rows = "\n".join(
            f"| {p.severity.upper()} | {p.category} | {p.description[:80]} |"
            for p in dep_graph.pain_points[:10]
        ) or "| – | – | Keine Pain Points erkannt |"

        # Debt categories tabelle
        debt_rows = "\n".join(
            f"| {c.name} | {round(c.score, 1)} | {c.weight}% | "
            f"{'; '.join(c.findings[:1]) or '–'} |"
            for c in debt.categories
        )

        # Top files
        file_rows = "\n".join(
            f"| `{f['path']}` | {f['language']} | {f['lines']:,} | {f['size_bytes']:,} |"
            for f in scan.to_dict()["largest_files"][:5]
        )

        return textwrap.dedent(f"""\
            # Technology Assessment – {project_name}

            **Erstellt:** {now}
            **Analysiert von:** TokenBroker Assessment Agent
            {f'**Repository:** {repo_url}' if repo_url else ''}

            ---

            ## Executive Summary

            {narrative.get('executive_summary', '')}

            **Tech-Debt-Score: {debt.total_score}/100 – Note {debt.grade}**
            _{grade_desc}_

            ---

            ## 1. Projektstruktur

            | Metrik | Wert |
            |--------|------|
            | Gesamtdateien | {scan.total_files:,} |
            | Gesamtzeilen (LOC) | {scan.total_lines:,} |
            | Gesamtgroesse | {scan.total_size_bytes / 1024:.1f} KB |
            | Sprachen | {len(scan.lines_by_language)} |
            | Frameworks | {', '.join(scan.frameworks_detected) or '–'} |

            ### LOC nach Sprache

            | Sprache | LOC | Dateien |
            |---------|-----|---------|
            {chr(10).join(
                f'| {lang} | {lines:,} | {scan.files_by_language.get(lang, 0)} |'
                for lang, lines in list(scan.lines_by_language.items())[:8]
            )}

            ### Groesste Dateien

            | Datei | Sprache | Zeilen | Bytes |
            |-------|---------|--------|-------|
            {file_rows}

            ---

            ## 2. Abhaengigkeitsanalyse

            | Metrik | Wert |
            |--------|------|
            | Analysierte Dateien | {dep_graph.summary()['total_files']} |
            | Abhaengigkeitskanten | {dep_graph.summary()['total_edges']} |
            | Erkannte Pain Points | {dep_graph.summary()['pain_points']} |

            ### Pain Points

            | Schwere | Kategorie | Beschreibung |
            |---------|-----------|--------------|
            {pain_rows}

            ---

            ## 3. Tech-Debt-Analyse

            **Gesamtscore: {debt.total_score}/100 (Note: {debt.grade})**

            | Kategorie | Score | Gewicht | Wichtigster Befund |
            |-----------|-------|---------|-------------------|
            {debt_rows}

            ### Kritische Befunde

            {chr(10).join(f'- {f}' for f in debt.critical_findings) or '- Keine kritischen Befunde'}

            ---

            ## 4. Handlungsempfehlungen

            {narrative.get('recommendations', '')}

            ---

            ## 5. Naechste Schritte

            1. **Sofort (0-2 Wochen):** Kritische Pain Points adressieren
               (zirkulaere Abhaengigkeiten, grosse Dateien > 2000 Zeilen)
            2. **Kurzfristig (1-3 Monate):** Testabdeckung auf ≥ 20% LOC erhoehen,
               veraltete Bibliotheken aktualisieren
            3. **Mittelfristig (3-6 Monate):** Architektur-Refactoring,
               Dokumentation vervollstaendigen

            ---

            *Bericht generiert von TokenBroker Assessment Agent v1.0*
        """)


import re  # noqa: E402  (moved to bottom to avoid circular at top)
