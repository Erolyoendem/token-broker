"""
BatchOrchestrator – Coordinates enterprise-scale Ruby→Python conversions.

Features:
  - Drives the MigrationPlan batch-by-batch using the existing Swarm Orchestrator
  - Checkpoint/resume: saves state after every successful batch to a JSON file
  - Rollback: reverts Git branch to checkpoint on critical failure
  - QA gate: skips next batch if current batch success rate is below threshold
  - Discord reporting after each batch

Checkpoint file format (JSON):
  {
    "session_id": str,
    "plan_hash": str,             # hash of ordered file list
    "completed_batches": [int],   # batch indices already done
    "results": [...],             # aggregated ConversionResult dicts
    "branch": str,                # git branch for this session
    "started_at": str,
    "last_updated": str,
  }
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .migration_planner import MigrationPlan, MigrationBatch

DISCORD_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
QA_PASS_THRESHOLD = float(os.getenv("ENTERPRISE_QA_THRESHOLD", "0.7"))


def _discord_sync(msg: str) -> None:
    """Fire-and-forget Discord post (sync, used between async boundaries)."""
    if not DISCORD_URL:
        return
    try:
        import urllib.request
        data = json.dumps({"content": msg}).encode()
        req = urllib.request.Request(
            DISCORD_URL, data=data,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def _git(cmd: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git"] + cmd, cwd=cwd, capture_output=True, text=True
    )
    return result.stdout.strip()


class CheckpointManager:
    """Persists migration state to a JSON file for resume support."""

    def __init__(self, checkpoint_path: Path) -> None:
        self.path = checkpoint_path

    def load(self) -> Optional[dict]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                pass
        return None

    def save(self, state: dict) -> None:
        state["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.path.write_text(json.dumps(state, indent=2))

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


class BatchOrchestrator:
    """
    Runs a MigrationPlan using the swarm, with checkpointing and rollback.

    Usage::

        orch = BatchOrchestrator(
            plan=plan,
            source_root=Path("my_ruby_project"),
            output_root=Path("converted_python"),
            checkpoint_path=Path(".migration_checkpoint.json"),
        )
        summary = asyncio.run(orch.run())
    """

    def __init__(
        self,
        plan: MigrationPlan,
        source_root: Path,
        output_root: Path,
        checkpoint_path: Path = Path(".migration_checkpoint.json"),
        workers: int = 5,
        git_branch_prefix: str = "enterprise-migration",
    ) -> None:
        self.plan = plan
        self.source_root = source_root
        self.output_root = output_root
        self.checkpoint = CheckpointManager(checkpoint_path)
        self.workers = workers
        self.git_branch_prefix = git_branch_prefix

        self._plan_hash = hashlib.md5(
            json.dumps(plan.ordered_files).encode()
        ).hexdigest()[:8]

    async def run(self) -> dict[str, Any]:
        """Execute the plan. Resumes from checkpoint if one exists."""
        state = self._init_state()
        completed = set(state["completed_batches"])

        branch = state["branch"]
        self._ensure_git_branch(branch)

        all_results: list[dict] = list(state["results"])
        t_start = time.perf_counter()

        for batch in self.plan.batches:
            if batch.index in completed:
                print(f"[Enterprise] Batch {batch.index}: skipped (checkpoint)")
                continue

            print(f"[Enterprise] Batch {batch.index} ({batch.priority}): "
                  f"{len(batch.files)} files")

            batch_results = await self._run_batch(batch)
            all_results.extend(batch_results)

            ok_count = sum(1 for r in batch_results if r.get("ok"))
            success_rate = ok_count / max(len(batch_results), 1)

            # Save checkpoint
            state["completed_batches"].append(batch.index)
            state["results"] = all_results
            self.checkpoint.save(state)

            # Commit converted files to git branch
            self._git_commit_batch(branch, batch.index, ok_count, len(batch_results))

            msg = (
                f"[Enterprise] Batch {batch.index} done: "
                f"{ok_count}/{len(batch_results)} OK "
                f"({success_rate:.0%}) | branch: {branch}"
            )
            _discord_sync(msg)
            print(f"  {msg}")

            # QA gate
            if success_rate < QA_PASS_THRESHOLD:
                warn = (
                    f"[Enterprise] QA GATE FAILED at batch {batch.index}: "
                    f"success_rate={success_rate:.0%} < {QA_PASS_THRESHOLD:.0%}. "
                    f"Migration paused. Fix issues and resume."
                )
                _discord_sync(warn)
                print(warn)
                self._rollback(branch, batch.index)
                break

        elapsed = round(time.perf_counter() - t_start, 2)
        total_ok = sum(1 for r in all_results if r.get("ok"))
        summary = {
            "session_id": state["session_id"],
            "branch": branch,
            "total_files": self.plan.total_files,
            "converted": len(all_results),
            "ok": total_ok,
            "errors": len(all_results) - total_ok,
            "success_rate": round(total_ok / max(len(all_results), 1), 3),
            "elapsed_s": elapsed,
            "completed_batches": state["completed_batches"],
        }

        _discord_sync(
            f"[Enterprise] Migration complete: {total_ok}/{len(all_results)} OK "
            f"| branch: {branch} | {elapsed}s"
        )
        return summary

    # ── Internal ───────────────────────────────────────────────────────────────

    def _init_state(self) -> dict:
        existing = self.checkpoint.load()
        if existing and existing.get("plan_hash") == self._plan_hash:
            print(f"[Enterprise] Resuming from checkpoint: "
                  f"{len(existing['completed_batches'])} batches already done")
            return existing
        session_id = uuid.uuid4().hex[:8]
        branch = f"{self.git_branch_prefix}/{session_id}"
        return {
            "session_id": session_id,
            "plan_hash": self._plan_hash,
            "completed_batches": [],
            "results": [],
            "branch": branch,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "last_updated": "",
        }

    async def _run_batch(self, batch: MigrationBatch) -> list[dict]:
        """Convert files in the batch using the swarm orchestrator."""
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from agent_swarm.orchestrator import Orchestrator
            from agent_swarm.memory import SwarmMemory

            memory = SwarmMemory()
            orchestrator = Orchestrator(memory, workers=min(self.workers, len(batch.files)))

            tasks = []
            for fpath in batch.files:
                try:
                    source = Path(fpath).read_text(encoding="utf-8", errors="replace")
                    tasks.append(
                        orchestrator.convert_one(Path(fpath).name, source)
                    )
                except OSError:
                    tasks.append(asyncio.coroutine(lambda: {"ok": False, "error": "read error"})())

            return list(await asyncio.gather(*tasks, return_exceptions=False))
        except Exception as exc:
            print(f"  [Enterprise] Batch {batch.index} swarm error: {exc}")
            return [{"ok": False, "error": str(exc), "filename": f} for f in batch.files]

    def _ensure_git_branch(self, branch: str) -> None:
        try:
            existing = _git(["branch", "--list", branch], self.source_root)
            if not existing:
                _git(["checkout", "-b", branch], self.source_root)
            else:
                _git(["checkout", branch], self.source_root)
        except Exception:
            pass  # non-git projects: skip

    def _git_commit_batch(
        self, branch: str, batch_idx: int, ok: int, total: int
    ) -> None:
        try:
            _git(["add", "-A"], self.output_root)
            msg = f"[Enterprise] Batch {batch_idx}: {ok}/{total} files converted"
            _git(["commit", "-m", msg, "--allow-empty"], self.output_root)
        except Exception:
            pass

    def _rollback(self, branch: str, failed_batch: int) -> None:
        print(f"[Enterprise] Rolling back branch {branch} to last checkpoint…")
        try:
            _git(["revert", "--no-commit", "HEAD"], self.source_root)
            _git(["checkout", "--", "."], self.source_root)
        except Exception as e:
            print(f"[Enterprise] Rollback failed: {e}")
