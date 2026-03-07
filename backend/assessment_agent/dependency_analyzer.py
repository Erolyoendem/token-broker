"""
AssessmentDependencyAnalyzer – Erweiterter Abhaengigkeitsanalysator.

Baut auf enterprise_migration.DependencyAnalyzer auf und fuegt hinzu:
  - Sprach-agnostische Analyse (Python imports, JS require/import)
  - Zirkulaere Abhaengigkeiten (DFS-Erkennung)
  - Uebermassig grosse Dateien (> LARGE_FILE_THRESHOLD Zeilen)
  - Veraltete Bibliotheken (Gemfile/requirements.txt Heuristik)
  - Hochgradig vernetzte Dateien (viele eingehende Kanten)
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Optionaler Import des Enterprise-Analyzers
try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from enterprise_migration.dependency_analyzer import DependencyAnalyzer as _RubyAnalyzer
    from enterprise_migration.dependency_analyzer import DependencyGraph
    _RUBY_ANALYZER_AVAILABLE = True
except ImportError:
    _RUBY_ANALYZER_AVAILABLE = False

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

LARGE_FILE_THRESHOLD = 500        # Zeilen
LARGE_FILE_CRITICAL  = 2000       # Zeilen
HIGH_FAN_IN_THRESHOLD = 5         # eingehende Abhaengigkeiten
OUTDATED_PATTERNS: list[tuple[str, str]] = [
    # (Datei-Pattern, Content-Regex)
    ("Gemfile",              r"ruby\s+['\"]1\.\d|ruby\s+['\"]2\.[0-5]"),
    ("requirements*.txt",    r"django==1\.|django==2\.[012]|flask==0\.|flask==1\."),
    ("package.json",         r'"node":\s*"[0-9]\.|"node":\s*"1[0-5]\.'),
]

# ---------------------------------------------------------------------------
# Pain-Point Kategorien
# ---------------------------------------------------------------------------

PAIN_CIRCULAR     = "circular_dependency"
PAIN_LARGE_FILE   = "large_file"
PAIN_HIGH_FAN_IN  = "high_fan_in"
PAIN_OUTDATED_DEP = "outdated_dependency"
PAIN_ISOLATED     = "isolated_module"


@dataclass
class PainPoint:
    category: str          # one of PAIN_* constants
    severity: str          # "low" | "medium" | "high" | "critical"
    description: str
    files: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "files": self.files,
            "metadata": self.metadata,
        }


@dataclass
class AssessmentGraph:
    adjacency: dict[str, list[str]]    # file → [dep_files]
    reverse: dict[str, list[str]]      # file → [dependents]
    all_files: list[str]
    pain_points: list[PainPoint]
    ruby_graph: Any = None             # DependencyGraph if Ruby project

    def summary(self) -> dict[str, Any]:
        return {
            "total_files": len(self.all_files),
            "total_edges": sum(len(v) for v in self.adjacency.values()),
            "pain_points": len(self.pain_points),
            "pain_by_category": self._pain_by_category(),
        }

    def _pain_by_category(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in self.pain_points:
            counts[p.category] = counts.get(p.category, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Language-agnostic import parsers
# ---------------------------------------------------------------------------

_RE_PY_IMPORT = re.compile(
    r"""^(?:from\s+([\w.]+)\s+import|import\s+([\w., ]+))""", re.M
)
_RE_JS_IMPORT = re.compile(
    r"""(?:require\(['"]([^'"]+)['"]\)|from\s+['"]([^'"]+)['"])""", re.M
)


def _parse_python_imports(content: str) -> list[str]:
    imports = []
    for m in _RE_PY_IMPORT.finditer(content):
        mod = m.group(1) or m.group(2)
        if mod:
            imports.extend(p.strip() for p in mod.split(","))
    return imports


def _parse_js_imports(content: str) -> list[str]:
    imports = []
    for m in _RE_JS_IMPORT.finditer(content):
        mod = m.group(1) or m.group(2)
        if mod:
            imports.append(mod)
    return imports


# ---------------------------------------------------------------------------
# AssessmentDependencyAnalyzer
# ---------------------------------------------------------------------------

class AssessmentDependencyAnalyzer:
    """
    Sprach-agnostischer Abhaengigkeitsanalysator mit Pain-Point-Erkennung.

    Unterstuetzt: Python, JavaScript/TypeScript, Ruby (via enterprise_migration).
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def analyze(self) -> AssessmentGraph:
        adjacency: dict[str, list[str]] = defaultdict(list)
        all_files: list[str] = []

        # Ruby: delegate to enterprise_migration analyzer
        ruby_graph = None
        if _RUBY_ANALYZER_AVAILABLE and any(self.root.rglob("*.rb")):
            try:
                analyzer = _RubyAnalyzer(self.root)
                ruby_graph = analyzer.analyze()
                for fpath, deps in ruby_graph.adjacency.items():
                    rel = self._rel(fpath)
                    adjacency[rel].extend(self._rel(d) for d in deps)
                    all_files.append(rel)
            except Exception:
                pass

        # Python / JS / TS: lightweight regex-based
        for ext, parser in [
            (".py",  _parse_python_imports),
            (".js",  _parse_js_imports),
            (".ts",  _parse_js_imports),
            (".tsx", _parse_js_imports),
        ]:
            for path in self.root.rglob(f"*{ext}"):
                if any(skip in path.parts for skip in
                       {".git", "node_modules", "__pycache__", "venv", ".venv"}):
                    continue
                rel = self._rel(str(path))
                if rel not in all_files:
                    all_files.append(rel)
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                imports = parser(content)
                # Resolve relative imports only
                resolved = self._resolve_relative_imports(path, imports)
                for dep in resolved:
                    if dep not in adjacency[rel]:
                        adjacency[rel].append(dep)

        # Build reverse graph (fan-in)
        reverse: dict[str, list[str]] = defaultdict(list)
        for src, deps in adjacency.items():
            for dep in deps:
                reverse[dep].append(src)

        pain_points = self._detect_pain_points(adjacency, reverse, all_files)

        return AssessmentGraph(
            adjacency=dict(adjacency),
            reverse=dict(reverse),
            all_files=all_files,
            pain_points=pain_points,
            ruby_graph=ruby_graph,
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _rel(self, path: str) -> str:
        try:
            return str(Path(path).relative_to(self.root))
        except ValueError:
            return path

    def _resolve_relative_imports(self, from_file: Path, imports: list[str]) -> list[str]:
        resolved = []
        for imp in imports:
            if not imp.startswith("."):
                continue
            parts = imp.lstrip(".").replace(".", "/")
            base = from_file.parent
            for suffix in ("", ".py", ".js", ".ts", "/index.js", "/index.ts"):
                candidate = (base / (parts + suffix)).resolve()
                if candidate.exists():
                    resolved.append(self._rel(str(candidate)))
                    break
        return resolved

    def _detect_pain_points(
        self,
        adjacency: dict[str, list[str]],
        reverse: dict[str, list[str]],
        all_files: list[str],
    ) -> list[PainPoint]:
        pain: list[PainPoint] = []

        # 1. Circular dependencies (DFS)
        cycles = self._find_cycles(adjacency)
        for cycle in cycles:
            pain.append(PainPoint(
                category=PAIN_CIRCULAR,
                severity="critical",
                description=f"Zirkulaere Abhaengigkeit: {' → '.join(cycle)}",
                files=list(cycle),
            ))

        # 2. Large files
        for path in self.root.rglob("*"):
            if not path.is_file() or any(
                skip in path.parts for skip in {".git", "node_modules", "venv", "__pycache__"}
            ):
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").count("\n")
            except OSError:
                continue
            if lines >= LARGE_FILE_CRITICAL:
                pain.append(PainPoint(
                    category=PAIN_LARGE_FILE,
                    severity="high",
                    description=f"{self._rel(str(path))}: {lines} Zeilen (kritisch)",
                    files=[self._rel(str(path))],
                    metadata={"lines": lines},
                ))
            elif lines >= LARGE_FILE_THRESHOLD:
                pain.append(PainPoint(
                    category=PAIN_LARGE_FILE,
                    severity="medium",
                    description=f"{self._rel(str(path))}: {lines} Zeilen (gross)",
                    files=[self._rel(str(path))],
                    metadata={"lines": lines},
                ))

        # 3. High fan-in (too many dependents)
        for fpath, dependents in reverse.items():
            if len(dependents) >= HIGH_FAN_IN_THRESHOLD:
                pain.append(PainPoint(
                    category=PAIN_HIGH_FAN_IN,
                    severity="medium",
                    description=(
                        f"{fpath} wird von {len(dependents)} Dateien abhaengig gemacht"
                        " (hohes Kopplungsrisiko)"
                    ),
                    files=[fpath] + dependents,
                    metadata={"fan_in": len(dependents)},
                ))

        # 4. Outdated dependencies
        for file_pattern, content_re in OUTDATED_PATTERNS:
            for path in self.root.rglob(file_pattern):
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if re.search(content_re, content, re.I):
                    pain.append(PainPoint(
                        category=PAIN_OUTDATED_DEP,
                        severity="high",
                        description=f"Veraltete Abhaengigkeit in {self._rel(str(path))}",
                        files=[self._rel(str(path))],
                    ))

        return pain

    @staticmethod
    def _find_cycles(adjacency: dict[str, list[str]]) -> list[tuple[str, ...]]:
        """Tarjan-Lite: findet alle Zyklen via DFS."""
        cycles: list[tuple[str, ...]] = []
        visited: set[str] = set()
        path_stack: list[str] = []
        path_set: set[str] = set()

        def dfs(node: str) -> None:
            if node in path_set:
                idx = path_stack.index(node)
                cycle = tuple(path_stack[idx:])
                if cycle not in cycles:
                    cycles.append(cycle)
                return
            if node in visited:
                return
            visited.add(node)
            path_stack.append(node)
            path_set.add(node)
            for neighbor in adjacency.get(node, []):
                dfs(neighbor)
            path_stack.pop()
            path_set.discard(node)

        for node in list(adjacency.keys()):
            dfs(node)

        return cycles[:20]  # cap at 20 to avoid noise
