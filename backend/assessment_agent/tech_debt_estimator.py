"""
TechDebtEstimator – Bewertet technische Schulden einer Codebasis.

Heuristiken:
  1. Code-Duplizierung   – aehnliche Zeilensequenzen in verschiedenen Dateien
  2. Fehlende Tests      – Verhaeltnis Test-LOC zu gesamt LOC
  3. Veraltete Syntax    – Python 2, alte Ruby-Idiome, var (JS)
  4. Grosse Dateien      – mehr als 500 / 2000 Zeilen
  5. Fehlende Dokumentation – keine Docstrings/Kommentare
  6. Komplexe Funktionen – tiefe Verschachtelung, lange Funktionen
  7. TODO/FIXME/HACK     – Inline-Schulden-Marker

Ergebnis: TechDebtResult mit Score 0-100 (0=keine Schulden, 100=kritisch).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .code_scanner import ScanResult, _SKIP_DIRS

# ---------------------------------------------------------------------------
# Gewichte fuer Score-Berechnung
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "duplication":       20,
    "missing_tests":     20,
    "outdated_syntax":   15,
    "large_files":       15,
    "missing_docs":      10,
    "complexity":        10,
    "todo_markers":      10,
}

# ---------------------------------------------------------------------------
# Marker-Patterns
# ---------------------------------------------------------------------------

_TODO_RE       = re.compile(r"\b(TODO|FIXME|HACK|XXX|WORKAROUND)\b", re.I)
_PY2_RE        = re.compile(r"\bprint\s+[\"']|xrange\(|raw_input\(")
_OLD_RUBY_RE   = re.compile(r"\$LOAD_PATH|require\s+'pp'|\.send\(:deprecated")
_VAR_JS_RE     = re.compile(r"\bvar\s+\w+")
_FUNC_LEN_RE   = re.compile(r"\bdef\s+\w+|\bfunction\s+\w+", re.M)
_DOCSTRING_RE  = re.compile(r'""".*?"""|\'\'\'.*?\'\'\'|#[^\n]*', re.S)
_NESTING_RE    = re.compile(r"(if|for|while|with|try)\b", re.M)


@dataclass
class DebtCategory:
    name: str
    score: float          # 0-100 fuer diese Kategorie
    weight: float         # Gewichtung im Gesamtscore
    findings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def weighted_contribution(self) -> float:
        return self.score * (self.weight / 100)


@dataclass
class TechDebtResult:
    total_score: int                    # 0-100
    grade: str                          # A-F
    categories: list[DebtCategory]
    critical_findings: list[str]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_score": self.total_score,
            "grade": self.grade,
            "categories": [
                {
                    "name": c.name,
                    "score": round(c.score, 1),
                    "weight": c.weight,
                    "findings": c.findings[:5],
                    "details": c.details,
                }
                for c in self.categories
            ],
            "critical_findings": self.critical_findings,
            "summary": self.summary,
        }


def _score_to_grade(score: int) -> str:
    if score <= 15:  return "A"
    if score <= 30:  return "B"
    if score <= 50:  return "C"
    if score <= 70:  return "D"
    return "F"


# ---------------------------------------------------------------------------
# TechDebtEstimator
# ---------------------------------------------------------------------------

class TechDebtEstimator:
    """Bewertet technische Schulden einer Codebasis auf 0-100-Skala."""

    def __init__(self, root: str | Path, scan_result: ScanResult | None = None) -> None:
        self.root = Path(root).resolve()
        self._scan = scan_result

    def estimate(self) -> TechDebtResult:
        files = self._collect_files()
        categories = [
            self._check_duplication(files),
            self._check_missing_tests(files),
            self._check_outdated_syntax(files),
            self._check_large_files(files),
            self._check_missing_docs(files),
            self._check_complexity(files),
            self._check_todo_markers(files),
        ]

        raw_score = sum(c.weighted_contribution() for c in categories)
        total = min(100, max(0, round(raw_score)))
        grade = _score_to_grade(total)

        critical = [
            f for c in categories if c.score >= 70 for f in c.findings[:2]
        ]

        summary = {
            "total_files_analyzed": len(files),
            "score_by_category": {
                c.name: round(c.score, 1) for c in categories
            },
        }

        return TechDebtResult(
            total_score=total,
            grade=grade,
            categories=categories,
            critical_findings=critical,
            summary=summary,
        )

    # ── Collectors ─────────────────────────────────────────────────────────────

    def _collect_files(self) -> list[tuple[Path, str]]:
        """Returns list of (path, content) tuples for analysable source files."""
        _ANALYSABLE = {".py", ".rb", ".js", ".ts", ".tsx", ".jsx",
                       ".java", ".go", ".rs", ".php", ".cs"}
        results = []
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            if any(skip in path.parts for skip in _SKIP_DIRS):
                continue
            if path.suffix.lower() not in _ANALYSABLE:
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                results.append((path, content))
            except OSError:
                continue
        return results

    # ── Heuristiken ────────────────────────────────────────────────────────────

    def _check_duplication(self, files: list[tuple[Path, str]]) -> DebtCategory:
        """Erkennt duplizierte Zeilen-Bloecke (≥ 6 identische Zeilen)."""
        BLOCK_SIZE = 6
        seen: dict[str, list[str]] = {}
        dup_count = 0

        for path, content in files:
            lines = [l.strip() for l in content.splitlines() if l.strip()]
            for i in range(len(lines) - BLOCK_SIZE + 1):
                block = "\n".join(lines[i:i + BLOCK_SIZE])
                if block not in seen:
                    seen[block] = []
                seen[block].append(str(path.relative_to(self.root)))

        dup_blocks = {k: v for k, v in seen.items() if len(v) > 1}
        dup_count = len(dup_blocks)
        total_blocks = max(len(seen), 1)
        ratio = dup_count / total_blocks

        score = min(100, ratio * 200)  # 50% dups → score=100
        findings = [
            f"Block dupliziert in: {', '.join(locs[:2])}"
            for block, locs in list(dup_blocks.items())[:5]
        ]
        return DebtCategory(
            name="duplication",
            score=score,
            weight=_WEIGHTS["duplication"],
            findings=findings,
            details={"duplicate_blocks": dup_count, "total_blocks": total_blocks},
        )

    def _check_missing_tests(self, files: list[tuple[Path, str]]) -> DebtCategory:
        test_lines = 0
        total_lines = 0
        test_files = 0

        for path, content in files:
            lines = len(content.splitlines())
            total_lines += lines
            name = path.name.lower()
            if name.startswith("test_") or name.endswith("_test.py") or \
               name.startswith("spec_") or "_spec.rb" in name or \
               "/tests/" in str(path) or "/spec/" in str(path):
                test_lines += lines
                test_files += 1

        ratio = test_lines / max(total_lines, 1)
        # Ideal: ≥20% test coverage by LOC → score=0; 0% → score=100
        score = max(0, 100 - ratio * 500)

        return DebtCategory(
            name="missing_tests",
            score=score,
            weight=_WEIGHTS["missing_tests"],
            findings=[
                f"Test-LOC Anteil: {ratio*100:.1f}% (Ziel: ≥20%)",
                f"Test-Dateien gefunden: {test_files}",
            ],
            details={"test_lines": test_lines, "total_lines": total_lines,
                     "test_ratio": round(ratio, 3)},
        )

    def _check_outdated_syntax(self, files: list[tuple[Path, str]]) -> DebtCategory:
        hits: list[str] = []
        for path, content in files:
            ext = path.suffix.lower()
            if ext == ".py" and _PY2_RE.search(content):
                hits.append(f"{path.relative_to(self.root)}: Python-2-Syntax")
            if ext == ".rb" and _OLD_RUBY_RE.search(content):
                hits.append(f"{path.relative_to(self.root)}: veraltete Ruby-Syntax")
            if ext in (".js", ".jsx") and _VAR_JS_RE.search(content):
                hits.append(f"{path.relative_to(self.root)}: var-Deklarationen (ES5)")

        score = min(100, len(hits) * 10)
        return DebtCategory(
            name="outdated_syntax",
            score=score,
            weight=_WEIGHTS["outdated_syntax"],
            findings=hits[:10],
            details={"total_hits": len(hits)},
        )

    def _check_large_files(self, files: list[tuple[Path, str]]) -> DebtCategory:
        large: list[str] = []
        critical: list[str] = []
        for path, content in files:
            lines = len(content.splitlines())
            rel = str(path.relative_to(self.root))
            if lines >= 2000:
                critical.append(f"{rel}: {lines} Zeilen (kritisch)")
            elif lines >= 500:
                large.append(f"{rel}: {lines} Zeilen")

        score = min(100, len(critical) * 30 + len(large) * 10)
        return DebtCategory(
            name="large_files",
            score=score,
            weight=_WEIGHTS["large_files"],
            findings=critical + large[:5],
            details={"critical": len(critical), "large": len(large)},
        )

    def _check_missing_docs(self, files: list[tuple[Path, str]]) -> DebtCategory:
        py_files = [(p, c) for p, c in files if p.suffix == ".py"]
        if not py_files:
            return DebtCategory(
                name="missing_docs", score=0,
                weight=_WEIGHTS["missing_docs"], findings=[]
            )

        undoc_funcs = 0
        total_funcs = 0
        for path, content in py_files:
            # Count def statements
            defs = re.findall(r"^\s*def\s+\w+", content, re.M)
            total_funcs += len(defs)
            # Count def followed immediately by docstring
            doc_defs = re.findall(
                r'^\s*def\s+\w+[^:]*:\s*\n\s+"""', content, re.M
            )
            undoc_funcs += len(defs) - len(doc_defs)

        ratio = undoc_funcs / max(total_funcs, 1)
        score = ratio * 100
        return DebtCategory(
            name="missing_docs",
            score=score,
            weight=_WEIGHTS["missing_docs"],
            findings=[
                f"{undoc_funcs}/{total_funcs} Funktionen ohne Docstring ({ratio*100:.0f}%)"
            ],
            details={"undocumented": undoc_funcs, "total": total_funcs},
        )

    def _check_complexity(self, files: list[tuple[Path, str]]) -> DebtCategory:
        complex_funcs: list[str] = []
        for path, content in files:
            # Naive: count nesting keywords per function
            # Split by `def` and count nesting per block
            blocks = _FUNC_LEN_RE.split(content)
            for i, block in enumerate(blocks[1:], 1):
                # Take up to next def
                segment = block.split("\ndef ")[0].split("\nfunction ")[0]
                nesting_score = len(_NESTING_RE.findall(segment))
                func_lines = len(segment.splitlines())
                if nesting_score >= 5 or func_lines >= 100:
                    complex_funcs.append(
                        f"{path.relative_to(self.root)}: "
                        f"Funktion ~{func_lines} Zeilen, {nesting_score} Verschachtelungen"
                    )

        score = min(100, len(complex_funcs) * 8)
        return DebtCategory(
            name="complexity",
            score=score,
            weight=_WEIGHTS["complexity"],
            findings=complex_funcs[:10],
            details={"complex_functions": len(complex_funcs)},
        )

    def _check_todo_markers(self, files: list[tuple[Path, str]]) -> DebtCategory:
        todos: list[str] = []
        for path, content in files:
            matches = _TODO_RE.findall(content)
            if matches:
                todos.append(
                    f"{path.relative_to(self.root)}: {len(matches)}x TODO/FIXME/HACK"
                )

        score = min(100, len(todos) * 5)
        return DebtCategory(
            name="todo_markers",
            score=score,
            weight=_WEIGHTS["todo_markers"],
            findings=todos[:10],
            details={"files_with_todos": len(todos)},
        )
