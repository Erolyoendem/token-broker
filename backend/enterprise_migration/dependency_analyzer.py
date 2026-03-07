"""
DependencyAnalyzer – Builds a dependency graph from a Ruby project.

Parses `require`, `require_relative`, `include`, `extend`, `autoload`,
and `module`/`class` declarations to map inter-file relationships.
The result is a directed acyclic graph (DAG) suitable for topological sort.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class RubyFile:
    path: Path
    module_names: list[str] = field(default_factory=list)
    class_names: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)       # absolute/gem requires
    relative_requires: list[str] = field(default_factory=list)  # require_relative
    included_modules: list[str] = field(default_factory=list)
    autoloads: list[str] = field(default_factory=list)
    size_bytes: int = 0

    @property
    def name(self) -> str:
        return self.path.name


# Regex patterns
_RE_MODULE = re.compile(r"^\s*module\s+(\w+)", re.M)
_RE_CLASS = re.compile(r"^\s*class\s+(\w[\w:]*)", re.M)
_RE_REQUIRE = re.compile(r"""^\s*require\s+['"]([^'"]+)['"]""", re.M)
_RE_REQUIRE_REL = re.compile(r"""^\s*require_relative\s+['"]([^'"]+)['"]""", re.M)
_RE_INCLUDE = re.compile(r"^\s*(?:include|extend)\s+([\w:]+)", re.M)
_RE_AUTOLOAD = re.compile(r"""^\s*autoload\s+:\w+,\s*['"]([^'"]+)['"]""", re.M)


class DependencyAnalyzer:
    """
    Analyzes a directory of Ruby files and builds a dependency graph.

    Usage::

        analyzer = DependencyAnalyzer(Path("my_ruby_project"))
        graph = analyzer.analyze()
        print(graph.adjacency)   # {file: [dep_files]}
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._files: dict[str, RubyFile] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def analyze(self) -> "DependencyGraph":
        """Scan all .rb files and return a DependencyGraph."""
        self._files.clear()
        for rb_path in sorted(self.root.rglob("*.rb")):
            self._parse_file(rb_path)
        return self._build_graph()

    # ── Internal ───────────────────────────────────────────────────────────────

    def _parse_file(self, path: Path) -> None:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return

        rb = RubyFile(
            path=path,
            size_bytes=path.stat().st_size,
            module_names=_RE_MODULE.findall(source),
            class_names=_RE_CLASS.findall(source),
            requires=_RE_REQUIRE.findall(source),
            relative_requires=_RE_REQUIRE_REL.findall(source),
            included_modules=_RE_INCLUDE.findall(source),
            autoloads=_RE_AUTOLOAD.findall(source),
        )
        self._files[str(path)] = rb

    def _resolve_relative(self, from_file: RubyFile, rel: str) -> Optional[str]:
        """Resolve a require_relative path to an absolute path string."""
        base = from_file.path.parent
        for suffix in ("", ".rb"):
            candidate = (base / (rel + suffix)).resolve()
            if str(candidate) in self._files:
                return str(candidate)
        return None

    def _build_graph(self) -> "DependencyGraph":
        # Map module/class names → file path for include resolution
        name_to_file: dict[str, str] = {}
        for fpath, rb in self._files.items():
            for name in rb.module_names + rb.class_names:
                name_to_file.setdefault(name, fpath)

        adjacency: dict[str, list[str]] = defaultdict(list)

        for fpath, rb in self._files.items():
            deps: list[str] = []

            # require_relative → direct file dependency
            for rel in rb.relative_requires:
                resolved = self._resolve_relative(rb, rel)
                if resolved and resolved != fpath:
                    deps.append(resolved)

            # include/extend → module name → file
            for mod_name in rb.included_modules:
                target = name_to_file.get(mod_name)
                if target and target != fpath:
                    deps.append(target)

            adjacency[fpath] = list(dict.fromkeys(deps))  # deduplicate, preserve order

        return DependencyGraph(
            files=dict(self._files),
            adjacency=dict(adjacency),
            root=self.root,
        )


@dataclass
class DependencyGraph:
    files: dict[str, RubyFile]
    adjacency: dict[str, list[str]]   # file → [dependency_files]
    root: Path

    def summary(self) -> dict:
        total_size = sum(f.size_bytes for f in self.files.values())
        edge_count = sum(len(deps) for deps in self.adjacency.values())
        return {
            "total_files": len(self.files),
            "total_size_bytes": total_size,
            "total_edges": edge_count,
            "isolated_files": sum(
                1 for f, deps in self.adjacency.items() if not deps
            ),
        }
