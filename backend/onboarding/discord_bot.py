"""
discord_bot.py – Onboarding-Nachrichten via Discord Webhook.

Sendet Kontext und naechste Aufgaben an einen Discord-Kanal,
wenn eine neue Instanz startet oder ein neues Feature fertig ist.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import httpx

from .context_generator import ContextGenerator, OnboardingPromptGenerator

_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
_ONBOARDING_DIR = Path(__file__).parent.parent.parent / "docs" / "onboarding"

# Discord Webhook-Limit: 2000 Zeichen pro Nachricht
_MAX_MSG_LEN = 1900


def _send(content: str, webhook_url: str = "") -> bool:
    """Sendet eine Nachricht an den Discord Webhook."""
    url = webhook_url or _WEBHOOK_URL
    if not url:
        return False
    chunks = textwrap.wrap(content, width=_MAX_MSG_LEN, replace_whitespace=False)
    success = True
    for chunk in chunks:
        try:
            resp = httpx.post(url, json={"content": chunk}, timeout=10)
            resp.raise_for_status()
        except Exception:
            success = False
    return success


def greet_new_instance(keyword: str = "", webhook_url: str = "") -> bool:
    """
    Begruesst eine neue Claude-Instanz mit Kontext und naechsten Aufgaben.

    Parameters
    ----------
    keyword : str
        Optionales Stichwort (z.B. "payment") fuer fokussierten Kontext.
    webhook_url : str
        Optionaler Webhook-URL (ueberschreibt Env-Variable).
    """
    gen = ContextGenerator()
    todos = gen.get_open_todos()
    commits = gen.get_recent_commits(5)

    topic_line = f" | Thema: **{keyword}**" if keyword else ""

    msg = (
        f"**TokenBroker – Neue Instanz gestartet**{topic_line}\n\n"
        f"**Letzte Commits:**\n"
        + "\n".join(f"  `{c}`" for c in commits[:5])
        + "\n\n**Offene Aufgaben:**\n"
        + "\n".join(f"  - {t}" for t in todos[:5])
        + "\n\nFuer vollstaendigen Kontext: `docs/onboarding/CONTEXT.md`"
    )
    return _send(msg, webhook_url)


def notify_tab_complete(tab: str, description: str, webhook_url: str = "") -> bool:
    """
    Sendet eine Fertigstellungs-Nachricht fuer einen abgeschlossenen Tab.

    Parameters
    ----------
    tab : str
        Tab-Bezeichnung, z.B. "TAB 14".
    description : str
        Kurzbeschreibung des Ergebnisses.
    """
    msg = f"**{tab} FERTIG:** {description}"
    return _send(msg, webhook_url)


def post_context_summary(webhook_url: str = "") -> bool:
    """Postet eine kompakte Projektzusammenfassung in Discord."""
    gen = OnboardingPromptGenerator()
    config = gen._config
    project = config.get("project", {})

    lines = [
        f"**{project.get('name', 'TokenBroker')} – Projektstatus**",
        f"Live: {project.get('live_url', '')}",
        f"Repo: {project.get('repository', '')}",
        "",
        "**Offene Punkte:**",
    ]
    for todo in config.get("open_todos", [])[:5]:
        lines.append(f"  - {todo}")
    lines.append("\nDetails: `docs/onboarding/PROJECT_SUMMARY.md`")

    return _send("\n".join(lines), webhook_url)
