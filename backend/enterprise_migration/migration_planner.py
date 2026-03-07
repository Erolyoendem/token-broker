"""
MigrationPlanner – Determines a safe conversion order from a DependencyGraph.

Uses Kahn's algorithm for topological sort. Files with no dependencies
are converted first; dependents follow only after all their dependencies
have been successfully converted.

Also supports batching: files at the same topological "level" (no order
constraint between them) are grouped so the BatchOrchestrator can run
them in parallel.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .dependency_analyzer import DependencyGraph


@dataclass
class MigrationBatch:
    """A group of files that can be converted in parallel (no mutual dependencies)."""
    index: int
    files: list[str]   # absolute path strings
    priority: str = "normal"   # "critical" | "normal" | "low"


@dataclass
class MigrationPlan:
    batches: list[MigrationBatch]
    cyclic_files: list[str] = field(default_factory=list)
    total_files: int = 0

    @property
    def ordered_files(self) -> list[str]:
        """Flat list of files in safe conversion order."""
        return [f for b in self.batches for f in b.files]

    def summary(self) -> dict:
        return {
            "total_files": self.total_files,
            "total_batches": len(self.batches),
            "cyclic_files": len(self.cyclic_files),
            "max_parallelism": max((len(b.files) for b in self.batches), default=0),
        }


class MigrationPlanner:
    """
    Plans the migration order from a DependencyGraph.

    Usage::

        planner = MigrationPlanner(graph)
        plan = planner.plan(max_batch_size=20)
        for batch in plan.batches:
            print(f"Batch {batch.index}: {len(batch.files)} files")
    """

    def __init__(self, graph: DependencyGraph) -> None:
        self.graph = graph

    def plan(self, max_batch_size: int = 50) -> MigrationPlan:
        """
        Returns a MigrationPlan with batches ordered by dependency level.

        Parameters
        ----------
        max_batch_size : split large parallel groups into chunks of this size
        """
        levels = self._topological_levels()
        cyclic = self._detect_cycles(set(levels.get("ordered", [])))

        batches: list[MigrationBatch] = []
        idx = 0
        for level_files in levels["levels"]:
            # Split large levels into chunks for manageable batch sizes
            for chunk_start in range(0, len(level_files), max_batch_size):
                chunk = level_files[chunk_start : chunk_start + max_batch_size]
                priority = "critical" if idx == 0 else "normal"
                batches.append(MigrationBatch(index=idx, files=chunk, priority=priority))
                idx += 1

        # Cyclic files go last as a single batch (best-effort)
        if cyclic:
            batches.append(MigrationBatch(index=idx, files=cyclic, priority="low"))

        return MigrationPlan(
            batches=batches,
            cyclic_files=cyclic,
            total_files=len(self.graph.files),
        )

    # ── Internal ───────────────────────────────────────────────────────────────

    def _topological_levels(self) -> dict:
        """Kahn's algorithm; groups nodes by BFS level (= parallel batches)."""
        all_files = list(self.graph.files.keys())
        adj = self.graph.adjacency  # file → [deps it needs]

        # Build reverse adjacency (who depends on me?) and in-degree
        in_degree: dict[str, int] = {f: 0 for f in all_files}
        reverse: dict[str, list[str]] = defaultdict(list)

        for f, deps in adj.items():
            for d in deps:
                if d in in_degree:
                    in_degree[f] += 1
                    reverse[d].append(f)

        queue: deque[str] = deque(f for f in all_files if in_degree[f] == 0)
        levels: list[list[str]] = []
        ordered: list[str] = []

        while queue:
            level = list(queue)
            levels.append(level)
            queue.clear()
            for node in level:
                ordered.append(node)
                for dependent in reverse[node]:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)

        return {"levels": levels, "ordered": ordered}

    def _detect_cycles(self, ordered_set: set[str]) -> list[str]:
        """Files not reached by topological sort are part of cycles."""
        return [f for f in self.graph.files if f not in ordered_set]
