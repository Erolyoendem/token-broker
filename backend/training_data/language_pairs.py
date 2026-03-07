"""
Plugin architecture for language pair converters.

Each LanguagePair defines how to parse, generate, and validate
code for a specific source→target language combination.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar


@dataclass
class ParseResult:
    language: str
    source: str
    constructs: list[str]  # detected constructs: 'class', 'function', 'loop', ...


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]
    warnings: list[str]


class LanguagePair(ABC):
    """Base interface every language-pair plugin must implement."""

    source_lang: ClassVar[str]
    target_lang: ClassVar[str]
    file_extension: ClassVar[str]  # target extension

    @abstractmethod
    def parse(self, source_code: str) -> ParseResult:
        """Extract structure/constructs from source code."""

    @abstractmethod
    def build_prompt(self, source_code: str) -> str:
        """Return the LLM prompt that converts source → target."""

    @abstractmethod
    def validate(self, target_code: str) -> ValidationResult:
        """Validate the converted target code (syntax + basic checks)."""

    def clean_llm_output(self, raw: str) -> str:
        """Strip markdown fences that models sometimes add."""
        raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
        raw = raw.rstrip("`").strip()
        return raw

    @property
    def pair_id(self) -> str:
        return f"{self.source_lang}->{self.target_lang}"


# ── Ruby → Python ─────────────────────────────────────────────────────────────

class RubyToPython(LanguagePair):
    source_lang = "ruby"
    target_lang = "python"
    file_extension = ".py"

    _CONSTRUCTS = {
        "class":    r"\bclass\s+\w+",
        "module":   r"\bmodule\s+\w+",
        "method":   r"\bdef\s+\w+",
        "block":    r"\bdo\s*\|",
        "lambda":   r"\blambda\b|->",
        "mixin":    r"\binclude\b|\bextend\b",
        "symbol":   r":\w+",
        "hash":     r"\{[^}]*=>",
    }

    def parse(self, source_code: str) -> ParseResult:
        found = [
            name for name, pattern in self._CONSTRUCTS.items()
            if re.search(pattern, source_code)
        ]
        return ParseResult(language="ruby", source=source_code, constructs=found)

    def build_prompt(self, source_code: str) -> str:
        return (
            "Convert the following Ruby code to idiomatic Python 3.\n"
            "Rules:\n"
            "- Output ONLY valid Python code, no markdown fences, no explanations.\n"
            "- Use dataclasses or plain classes (no Ruby-style attr_accessor).\n"
            "- Replace Ruby blocks with list comprehensions or lambdas where appropriate.\n"
            "- Replace symbols (:key) with strings or Enum members.\n"
            "- All imports at the top. Max line length 100 characters.\n"
            "- Two blank lines between top-level definitions.\n\n"
            f"Ruby code:\n{source_code}"
        )

    def validate(self, target_code: str) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(target_code)
            fname = f.name
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", fname],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            errors.append(result.stderr.strip().splitlines()[0] if result.stderr else "syntax error")

        # Basic heuristics
        if "require " in target_code:
            warnings.append("Found 'require' – Ruby import not converted")
        if "puts " in target_code:
            warnings.append("Found 'puts' – Ruby print not converted")
        if re.search(r":\w+\s*=>", target_code):
            warnings.append("Found Ruby hash rocket (=>) – hash not converted")

        return ValidationResult(ok=not errors, errors=errors, warnings=warnings)


# ── Python → Java ─────────────────────────────────────────────────────────────

class PythonToJava(LanguagePair):
    source_lang = "python"
    target_lang = "java"
    file_extension = ".java"

    _CONSTRUCTS = {
        "class":       r"\bclass\s+\w+",
        "function":    r"\bdef\s+\w+",
        "comprehension": r"\[.+\bfor\b.+\bin\b",
        "decorator":   r"@\w+",
        "dataclass":   r"@dataclass",
        "type_hint":   r":\s*(int|str|float|bool|list|dict|Optional)",
    }

    def parse(self, source_code: str) -> ParseResult:
        found = [
            name for name, pattern in self._CONSTRUCTS.items()
            if re.search(pattern, source_code)
        ]
        return ParseResult(language="python", source=source_code, constructs=found)

    def build_prompt(self, source_code: str) -> str:
        return (
            "Convert the following Python 3 code to idiomatic Java 17.\n"
            "Rules:\n"
            "- Output ONLY valid Java code, no markdown fences, no explanations.\n"
            "- Wrap top-level code in a class named 'Main' with a main() method.\n"
            "- Convert Python dicts to HashMap<String, Object>.\n"
            "- Convert list comprehensions to Stream operations.\n"
            "- Add explicit types for all variables.\n"
            "- Use record classes for simple data containers.\n\n"
            f"Python code:\n{source_code}"
        )

    def validate(self, target_code: str) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        # Structural checks (no Java compiler required)
        if not re.search(r"\bclass\s+\w+", target_code):
            errors.append("No class definition found")
        if target_code.count("{") != target_code.count("}"):
            errors.append("Unbalanced braces")
        if "def " in target_code:
            warnings.append("Found Python 'def' – method not converted")
        if "print(" in target_code and "System.out" not in target_code:
            warnings.append("print() not converted to System.out.println()")
        return ValidationResult(ok=not errors, errors=errors, warnings=warnings)


# ── JavaScript → TypeScript ───────────────────────────────────────────────────

class JavaScriptToTypeScript(LanguagePair):
    source_lang = "javascript"
    target_lang = "typescript"
    file_extension = ".ts"

    _CONSTRUCTS = {
        "class":      r"\bclass\s+\w+",
        "arrow_fn":   r"=>\s*[{(]",
        "async":      r"\basync\b",
        "destructure": r"const\s*\{[^}]+\}",
        "spread":     r"\.\.\.\w+",
        "promise":    r"\.then\(",
    }

    def parse(self, source_code: str) -> ParseResult:
        found = [
            name for name, pattern in self._CONSTRUCTS.items()
            if re.search(pattern, source_code)
        ]
        return ParseResult(language="javascript", source=source_code, constructs=found)

    def build_prompt(self, source_code: str) -> str:
        return (
            "Convert the following JavaScript code to idiomatic TypeScript.\n"
            "Rules:\n"
            "- Output ONLY valid TypeScript, no markdown fences, no explanations.\n"
            "- Add explicit types to all function parameters and return values.\n"
            "- Replace 'var' with 'const' or 'let'.\n"
            "- Add interfaces or type aliases for object shapes.\n"
            "- Use 'unknown' instead of 'any' where possible.\n"
            "- Keep all existing logic intact.\n\n"
            f"JavaScript code:\n{source_code}"
        )

    def validate(self, target_code: str) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        if "var " in target_code:
            warnings.append("'var' not replaced with const/let")
        if ": any" in target_code:
            warnings.append("Found 'any' type – consider 'unknown'")
        if not re.search(r":\s*(string|number|boolean|void|unknown|never|\w+\[\])", target_code):
            warnings.append("No TypeScript type annotations found")
        return ValidationResult(ok=not errors, errors=errors, warnings=warnings)


# ── Registry ──────────────────────────────────────────────────────────────────

LANGUAGE_PAIRS: dict[str, LanguagePair] = {
    pair.pair_id: pair
    for pair in [RubyToPython(), PythonToJava(), JavaScriptToTypeScript()]
}


def get_pair(pair_id: str) -> LanguagePair:
    if pair_id not in LANGUAGE_PAIRS:
        raise ValueError(
            f"Unknown language pair '{pair_id}'. "
            f"Available: {list(LANGUAGE_PAIRS)}"
        )
    return LANGUAGE_PAIRS[pair_id]
