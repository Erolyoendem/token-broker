"""
context_generator.py – Zero-Cost-Onboarding fuer neue Claude-Instanzen und Entwickler.

Analysiert die Projektstruktur, liest Schluesseldokumente und generiert
massgeschneiderte Einstiegs-Prompts auf Basis eines Stichworts.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parent.parent.parent  # TokenBroker/
_CONFIG_FILE = _ROOT / "project_config.yaml"
_ONBOARDING_DIR = _ROOT / "docs" / "onboarding"
_DOCS_DIR = _ROOT / "docs"


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _read_file_safe(path: Path, max_lines: int = 80) -> str:
    """Liest eine Datei und gibt maximal `max_lines` Zeilen zurueck."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        return "\n".join(lines[:max_lines])
    except Exception:
        return ""


def _git_log(n: int = 10) -> list[str]:
    """Gibt die letzten n Git-Commit-Nachrichten zurueck."""
    try:
        result = subprocess.run(
            ["git", "log", f"--oneline", f"-{n}"],
            capture_output=True,
            text=True,
            cwd=_ROOT,
        )
        return result.stdout.strip().splitlines()
    except Exception:
        return []


def _collect_code_comments(directory: Path, extension: str = "*.py") -> dict[str, list[str]]:
    """Sammelt alle Docstrings und Kommentare aus Python-Dateien."""
    comments: dict[str, list[str]] = {}
    for filepath in sorted(directory.rglob(extension)):
        relative = str(filepath.relative_to(_ROOT))
        lines = []
        try:
            for line in filepath.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                    lines.append(stripped)
        except Exception:
            continue
        if lines:
            comments[relative] = lines[:10]  # max 10 Kommentare pro Datei
    return comments


def _load_config() -> dict[str, Any]:
    """Laedt project_config.yaml."""
    try:
        return yaml.safe_load(_CONFIG_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Stichwort-zu-Datei-Mapping
# ---------------------------------------------------------------------------

KEYWORD_MAP: dict[str, list[str]] = {
    "payment": [
        "backend/app/payment.py",
        "docs/payment.md",
        "frontend/index.html",
    ],
    "crowdfunding": [
        "backend/app/crowdfunding.py",
        "backend/app/trigger.py",
        "backend/tests/test_crowdfunding.py",
    ],
    "auth": [
        "backend/app/auth.py",
        "backend/tests/test_auth.py",
    ],
    "provider": [
        "backend/app/providers.py",
        "backend/app/router.py",
        "backend/app/db_providers.py",
    ],
    "evolution": [
        "backend/evolution/auto_optimizer.py",
        "backend/evolution/experiment_manager.py",
        "backend/evolution/metrics_collector.py",
        "backend/evolution/version_control.py",
    ],
    "swarm": [
        "backend/agent_swarm/",
        "docs/agent_swarm.md",
    ],
    "market": [
        "backend/market_intelligence/competitor_tracker.py",
        "backend/market_intelligence/opportunity_detector.py",
    ],
    "tenant": [
        "backend/app/tenant/isolation.py",
        "backend/app/tenant/resource_manager.py",
    ],
    "monitoring": [
        "docs/monitoring.md",
        "backend/app/metrics.py",
    ],
    "onboarding": [
        "docs/onboarding/CONTEXT.md",
        "docs/onboarding/NEXT_TASKS.md",
        "docs/onboarding/PROJECT_SUMMARY.md",
        "backend/onboarding/context_generator.py",
    ],
    "mvp3": [
        "docs/mvp3.md",
        "docs/strategy/",
    ],
    "tab 8": [],  # Uebersprungen in der Entwicklung
}


# ---------------------------------------------------------------------------
# ContextGenerator
# ---------------------------------------------------------------------------


class ContextGenerator:
    """Analysiert das Projekt und generiert Kontext-Snapshots."""

    def __init__(self) -> None:
        self.config = _load_config()
        self.generated_at = datetime.now(timezone.utc).isoformat()

    def analyze_structure(self) -> dict[str, Any]:
        """Liefert einen Ueberblick ueber die Projektstruktur."""
        structure: dict[str, Any] = {}
        for top_dir in ["backend", "docs", "frontend", "infra"]:
            path = _ROOT / top_dir
            if path.exists():
                structure[top_dir] = [
                    str(p.relative_to(_ROOT))
                    for p in sorted(path.rglob("*.py"))[:20]
                ]
        return structure

    def get_recent_commits(self, n: int = 15) -> list[str]:
        return _git_log(n)

    def get_open_todos(self) -> list[str]:
        return self.config.get("open_todos", [])

    def build_snapshot(self) -> dict[str, Any]:
        """Vollstaendiger Projekt-Snapshot fuer Embedding oder Speicherung."""
        return {
            "generated_at": self.generated_at,
            "project": self.config.get("project", {}),
            "technologies": self.config.get("technologies", {}),
            "recent_commits": self.get_recent_commits(),
            "open_todos": self.get_open_todos(),
            "structure": self.analyze_structure(),
            "code_comments": _collect_code_comments(_ROOT / "backend" / "app"),
            "onboarding_docs": {
                "summary": _read_file_safe(_ONBOARDING_DIR / "PROJECT_SUMMARY.md"),
                "context": _read_file_safe(_ONBOARDING_DIR / "CONTEXT.md"),
                "next_tasks": _read_file_safe(_ONBOARDING_DIR / "NEXT_TASKS.md"),
            },
        }

    def refresh_docs(self) -> None:
        """Aktualisiert PROJECT_SUMMARY mit aktuellen Commits (fuer Git-Hook)."""
        commits = self.get_recent_commits(20)
        summary_path = _ONBOARDING_DIR / "PROJECT_SUMMARY.md"
        if not summary_path.exists():
            return
        content = summary_path.read_text(encoding="utf-8")
        # Timestamp-Zeile aktualisieren
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines = content.splitlines()
        if lines:
            lines[0] = f"# TokenBroker – Projektzusammenfassung"
            if len(lines) > 1:
                lines[1] = f""
            if len(lines) > 2:
                lines[2] = f"**Generiert:** {today} | **Version:** automatisch"
        summary_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# OnboardingPromptGenerator
# ---------------------------------------------------------------------------


class OnboardingPromptGenerator:
    """Generiert massgeschneiderte Einstiegs-Prompts fuer neue Instanzen."""

    def __init__(self) -> None:
        self._ctx = ContextGenerator()
        self._config = self._ctx.config

    def _resolve_keyword(self, keyword: str) -> tuple[str, list[str]]:
        """Findet den passenden Kontext-Block fuer ein Stichwort."""
        kw = keyword.lower().strip()
        for key, files in KEYWORD_MAP.items():
            if key in kw or kw in key:
                return key, files
        return kw, []

    def generate(self, keyword: str = "") -> str:
        """
        Generiert einen vollstaendigen Onboarding-Prompt.

        Parameters
        ----------
        keyword : str
            Stichwort wie "payment", "crowdfunding", "weiter mit Tab 8" etc.

        Returns
        -------
        str
            Fertiger Prompt-Text, den eine neue Instanz direkt nutzen kann.
        """
        project = self._config.get("project", {})
        project_name = project.get("name", "TokenBroker")
        live_url = project.get("live_url", "")
        repo = project.get("repository", "")

        commits = self._ctx.get_recent_commits(5)
        todos = self._ctx.get_open_todos()

        context_section = _read_file_safe(_ONBOARDING_DIR / "CONTEXT.md", max_lines=60)
        summary_section = _read_file_safe(_ONBOARDING_DIR / "PROJECT_SUMMARY.md", max_lines=40)

        # Stichwort-spezifische Dateien
        topic, relevant_files = self._resolve_keyword(keyword)
        files_section = ""
        if relevant_files:
            files_section = "\n## Relevante Dateien fuer dieses Thema\n"
            for f in relevant_files:
                full = _ROOT / f
                if full.exists():
                    files_section += f"- `{f}` (vorhanden)\n"
                    snippet = _read_file_safe(full, max_lines=20)
                    if snippet:
                        files_section += f"  ```\n  {snippet[:300]}\n  ```\n"
                else:
                    files_section += f"- `{f}` (nicht gefunden)\n"

        # Naechste Aufgaben
        next_tasks = _read_file_safe(_ONBOARDING_DIR / "NEXT_TASKS.md", max_lines=40)

        prompt = f"""# Onboarding-Prompt: {project_name}
**Erstellt:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
**Thema:** {topic if topic else 'allgemein'}

---

## Projekt-Kontext

{summary_section}

---

## Architektur & Konventionen

{context_section}

---

## Letzte 5 Commits

{chr(10).join(f'- {c}' for c in commits)}

---

## Offene Aufgaben

{chr(10).join(f'- {t}' for t in todos)}

---

## Naechste Schritte (detailliert)

{next_tasks}
{files_section}
---

## Live-System

- **URL:** {live_url}
- **Repo:** {repo}

---

**Anweisung fuer neue Instanz:**
Du arbeitest am Projekt "{project_name}". Lies den obigen Kontext, dann fahre mit
dem Thema "{topic if topic else keyword}" fort. Alle wichtigen Dateipfade sind oben
aufgefuehrt. Committe am Ende mit dem Format `[TAB X] Beschreibung`.
"""
        return prompt

    def save_prompt(self, keyword: str, output_path: Path | None = None) -> Path:
        """Generiert und speichert einen Prompt in eine Datei."""
        prompt = self.generate(keyword)
        if output_path is None:
            slug = keyword.lower().replace(" ", "_")[:30] or "general"
            output_path = _ONBOARDING_DIR / f"prompt_{slug}.md"
        output_path.write_text(prompt, encoding="utf-8")
        return output_path
