"""
CTOOrchestrator – Wraps the existing SwarmOrchestrator with CTO oversight.

Before each task is dispatched to a Swarm worker, the CTOOrchestrator:
  1. Asks CTOAgent.decide() whether the task is approved.
  2. If approved: forwards to SwarmOrchestrator as normal.
  3. If rejected: records the rejection and skips the task.

After each batch, lessons are updated with success/failure insights.

Usage::

    cto_orch = CTOOrchestrator(memory=SwarmMemory(), workers=3)
    summary = asyncio.run(cto_orch.train(Path("ruby_files/")))
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from .core import CTOAgent


class CTOOrchestrator:
    """
    Supervised SwarmOrchestrator: all tasks are validated by the CTO agent
    before being dispatched.
    """

    def __init__(
        self,
        memory: Any = None,
        workers: int = 5,
        repo_root: Path | None = None,
    ) -> None:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

        from agent_swarm.memory import SwarmMemory
        from agent_swarm.orchestrator import Orchestrator

        self._memory = memory or SwarmMemory()
        self._swarm = Orchestrator(self._memory, workers=workers)
        self._cto = CTOAgent(repo_root or Path(__file__).resolve().parent.parent.parent)
        self._rejected: list[dict] = []

    # ── Public API ────────────────────────────────────────────────────────────

    async def train(self, ruby_dir: Path) -> dict[str, Any]:
        """
        Run the swarm over all .rb files – with CTO pre-approval per file.
        Files rejected by the CTO are skipped and logged.
        """
        ruby_files = sorted(ruby_dir.glob("*.rb"))
        if not ruby_files:
            return {"error": f"No .rb files in {ruby_dir}"}

        approved_files: list[Path] = []
        self._rejected = []

        for rb in ruby_files:
            decision = self._cto.decide(
                f"Convert {rb.name} to Python",
                context={"provider": "nvidia", "success_rate": 1.0},
            )
            if decision.approved:
                approved_files.append(rb)
            else:
                self._rejected.append({
                    "filename": rb.name,
                    "reason": decision.rationale,
                })

        if not approved_files:
            return {
                "ok": 0,
                "errors": 0,
                "rejected": len(self._rejected),
                "rejected_details": self._rejected,
                "error": "All files rejected by CTO agent",
            }

        # Write approved files to a temp dir for the standard swarm
        import tempfile, shutil
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for f in approved_files:
                shutil.copy(f, tmp_path / f.name)

            t_start = time.perf_counter()
            summary = await self._swarm.train(tmp_path)
            summary["elapsed_s"] = round(time.perf_counter() - t_start, 2)

        summary["cto_rejected"] = len(self._rejected)
        summary["cto_rejected_details"] = self._rejected
        self._update_lessons(summary)
        return summary

    async def convert_one(self, filename: str, ruby_code: str) -> dict[str, Any]:
        """CTO-supervised single conversion."""
        decision = self._cto.decide(
            f"Convert {filename} to Python",
            context={"provider": "nvidia", "success_rate": 1.0},
        )
        if not decision.approved:
            return {
                "ok": False,
                "filename": filename,
                "error": f"Rejected by CTO: {decision.rationale}",
            }
        return await self._swarm.convert_one(filename, ruby_code)

    @property
    def rejected(self) -> list[dict]:
        return list(self._rejected)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _update_lessons(self, summary: dict) -> None:
        try:
            mgr = self._cto.lessons
            rate = summary.get("avg_score", 0.0)
            tokens = summary.get("total_tokens", 0)
            ok = summary.get("ok", 0)
            total = summary.get("files", 1)
            mgr.add_insight(
                f"Run: {ok}/{total} OK, avg_score={rate:.3f}, "
                f"total_tokens={tokens}, cto_rejected={summary.get('cto_rejected', 0)}"
            )
            mgr.derive_rules_from_insights()
        except Exception as exc:
            print(f"[CTOOrchestrator] lessons update failed: {exc}")
