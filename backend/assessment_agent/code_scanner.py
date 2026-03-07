"""
CodeScanner – Rekursive Projektstruktur-Analyse.

Erfasst:
  - LOC pro Sprache (Python, Ruby, JS/TS, SQL, YAML, etc.)
  - Frameworks (Rails, Django, FastAPI, Express, Spring, ...)
  - Groesste Dateien
  - Datei- und Verzeichnis-Hierarchie
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Sprach-Erkennung
# ---------------------------------------------------------------------------

_LANG_MAP: dict[str, str] = {
    ".py": "Python",
    ".rb": "Ruby",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".sql": "SQL",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".html": "HTML",
    ".css": "CSS",
    ".sh": "Shell",
    ".md": "Markdown",
}

_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".idea", ".vscode", "vendor", "tmp",
}

# ---------------------------------------------------------------------------
# Framework-Fingerprints
# ---------------------------------------------------------------------------

_FRAMEWORK_FINGERPRINTS: list[tuple[str, str, str]] = [
    # (language, file_pattern, content_pattern)
    ("Ruby",       "Gemfile",          r"rails"),
    ("Ruby",       "*.rb",             r"class\s+\w+\s*<\s*ApplicationController"),
    ("Ruby",       "config.ru",        r"Rack"),
    ("Python",     "requirements*.txt", r"django"),
    ("Python",     "*.py",             r"from django"),
    ("Python",     "*.py",             r"from fastapi|import fastapi"),
    ("Python",     "*.py",             r"from flask|import flask"),
    ("JavaScript", "package.json",     r'"express"'),
    ("JavaScript", "package.json",     r'"next"'),
    ("JavaScript", "package.json",     r'"react"'),
    ("TypeScript", "package.json",     r'"nestjs"'),
    ("Java",       "pom.xml",          r"spring"),
    ("Go",         "go.mod",           r"gin-gonic|echo|fiber"),
]

_FRAMEWORK_NAMES: dict[str, str] = {
    "rails":                       "Ruby on Rails",
    "ApplicationController":       "Ruby on Rails",
    "Rack":                        "Rack",
    "django":                      "Django",
    "from django":                 "Django",
    "from fastapi":                "FastAPI",
    "import fastapi":              "FastAPI",
    "from flask":                  "Flask",
    "import flask":                "Flask",
    '"express"':                   "Express.js",
    '"next"':                      "Next.js",
    '"react"':                     "React",
    '"nestjs"':                    "NestJS",
    "spring":                      "Spring Boot",
    "gin-gonic":                   "Gin",
    "echo":                        "Echo",
    "fiber":                       "Fiber",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FileStat:
    path: str
    language: str
    lines: int
    size_bytes: int


@dataclass
class ScanResult:
    project_root: str
    total_files: int
    total_lines: int
    total_size_bytes: int
    lines_by_language: dict[str, int]
    files_by_language: dict[str, int]
    frameworks_detected: list[str]
    largest_files: list[FileStat]          # top-10
    all_files: list[FileStat] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_root": self.project_root,
            "total_files": self.total_files,
            "total_lines": self.total_lines,
            "total_size_bytes": self.total_size_bytes,
            "lines_by_language": self.lines_by_language,
            "files_by_language": self.files_by_language,
            "frameworks_detected": self.frameworks_detected,
            "largest_files": [
                {"path": f.path, "language": f.language,
                 "lines": f.lines, "size_bytes": f.size_bytes}
                for f in self.largest_files
            ],
        }


# ---------------------------------------------------------------------------
# CodeScanner
# ---------------------------------------------------------------------------

class CodeScanner:
    """Scannt ein Projektverzeichnis rekursiv und erstellt eine Strukturanalyse."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def scan(self) -> ScanResult:
        all_files: list[FileStat] = []
        lines_by_lang: dict[str, int] = {}
        files_by_lang: dict[str, int] = {}
        frameworks: set[str] = set()

        for path in self._iter_files():
            lang = _LANG_MAP.get(path.suffix.lower(), "Other")
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                lines = content.count("\n") + 1
            except OSError:
                content = ""
                lines = 0

            stat = FileStat(
                path=str(path.relative_to(self.root)),
                language=lang,
                lines=lines,
                size_bytes=path.stat().st_size,
            )
            all_files.append(stat)
            lines_by_lang[lang] = lines_by_lang.get(lang, 0) + lines
            files_by_lang[lang] = files_by_lang.get(lang, 0) + 1

            # Framework detection
            for _lang, pattern, content_re in _FRAMEWORK_FINGERPRINTS:
                if re.search(pattern.replace("*", ".*"), path.name):
                    match = re.search(content_re, content, re.I)
                    if match:
                        matched_text = match.group(0)
                        for key, name in _FRAMEWORK_NAMES.items():
                            if re.search(re.escape(key), matched_text, re.I):
                                frameworks.add(name)
                                break

        all_files.sort(key=lambda f: f.size_bytes, reverse=True)

        return ScanResult(
            project_root=str(self.root),
            total_files=len(all_files),
            total_lines=sum(f.lines for f in all_files),
            total_size_bytes=sum(f.size_bytes for f in all_files),
            lines_by_language=dict(sorted(lines_by_lang.items(), key=lambda x: -x[1])),
            files_by_language=dict(sorted(files_by_lang.items(), key=lambda x: -x[1])),
            frameworks_detected=sorted(frameworks),
            largest_files=all_files[:10],
            all_files=all_files,
        )

    def _iter_files(self):
        for item in self.root.rglob("*"):
            if item.is_file() and not any(
                skip in item.parts for skip in _SKIP_DIRS
            ):
                yield item
