"""
ClientPortal – Öffentlicher Status-Endpunkt für Delivery-Jobs.

Stellt bereit:
  - get_job_status(job_id, api_key) → dict  (für GET /delivery/{job_id})
  - format_progress_bar(pct)        → str   (ASCII-Fortschrittsbalken)
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

_PHASE_LABELS = {
    "pending":    "⏳ Wartend",
    "assessment": "🔍 Analyse",
    "planning":   "📋 Planung",
    "executing":  "⚙️  Ausführung",
    "validating": "✅ Validierung",
    "done":       "🎉 Abgeschlossen",
    "failed":     "❌ Fehlgeschlagen",
    "cancelled":  "🚫 Abgebrochen",
}


def format_progress_bar(pct: int, width: int = 20) -> str:
    filled = int(width * pct / 100)
    return "[" + "█" * filled + "░" * (width - filled) + f"] {pct}%"


def get_job_status(job_id: str, api_key: Optional[str] = None) -> dict | None:
    """
    Gibt den öffentlichen Status eines Delivery-Jobs zurück.

    Sensible interne Felder (plan-Details, interne Logs) werden
    für externe API-Keys weggelassen.

    Returns None wenn Job nicht gefunden.
    """
    from .orchestrator import get_job

    job = get_job(job_id)
    if not job:
        return None

    phase_label = _PHASE_LABELS.get(job.status, job.status)
    progress_bar = format_progress_bar(job.progress)

    # Öffentliche Antwort: keine internen Plandetails
    return {
        "job_id":        job.id,
        "status":        job.status,
        "status_label":  phase_label,
        "current_phase": job.current_phase,
        "progress":      job.progress,
        "progress_bar":  progress_bar,
        "started_at":    job.started_at,
        "completed_at":  job.completed_at,
        "result_path":   job.result_path,
        "recent_logs":   job.logs[-5:] if job.logs else [],
    }
