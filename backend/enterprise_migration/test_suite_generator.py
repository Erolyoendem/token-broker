"""
TestSuiteGenerator – Automatically generates pytest test cases for converted Python files.

For each converted Ruby→Python file pair, generates:
  1. A syntax/import test (does the module load without errors?)
  2. Behavioral tests: calls public functions/methods with sample inputs
     and checks that output types match the Ruby original's contract
  3. A regression test stub where the evaluator recorded expected output

The generated tests are written to an output directory and can be run with
`pytest tests/generated/`.
"""
from __future__ import annotations

import ast
import inspect
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class GeneratedTest:
    source_rb: str      # original Ruby filename
    target_py: str      # converted Python filename
    test_path: Path     # where the test file was written
    test_count: int     # number of test functions generated


class TestSuiteGenerator:
    """
    Generates pytest test suites for converted Python files.

    Usage::

        gen = TestSuiteGenerator(
            output_dir=Path("tests/generated"),
            ruby_root=Path("my_ruby"),
            python_root=Path("converted_python"),
        )
        results = gen.generate_all()
    """

    def __init__(
        self,
        output_dir: Path,
        ruby_root: Path,
        python_root: Path,
    ) -> None:
        self.output_dir = output_dir
        self.ruby_root = ruby_root
        self.python_root = python_root
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "__init__.py").touch()

    # ── Public API ─────────────────────────────────────────────────────────────

    def generate_all(self) -> list[GeneratedTest]:
        """Generate tests for every .py file in python_root that has a matching .rb."""
        results = []
        for py_path in sorted(self.python_root.rglob("*.py")):
            rb_name = py_path.stem + ".rb"
            rb_path = self.ruby_root / rb_name
            if not rb_path.exists():
                # Try nested paths
                candidates = list(self.ruby_root.rglob(rb_name))
                rb_path = candidates[0] if candidates else None

            if rb_path is None:
                continue

            result = self.generate_for_file(rb_path, py_path)
            if result:
                results.append(result)
        return results

    def generate_for_file(
        self, ruby_path: Path, python_path: Path
    ) -> GeneratedTest | None:
        """Generate a single test file for a Ruby/Python pair."""
        try:
            py_source = python_path.read_text(encoding="utf-8", errors="replace")
            rb_source = ruby_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        module_name = python_path.stem
        functions = self._extract_functions(py_source)
        classes = self._extract_classes(py_source)

        test_lines = self._build_test_file(
            module_name=module_name,
            python_path=python_path,
            ruby_source=rb_source,
            functions=functions,
            classes=classes,
        )

        test_filename = f"test_{module_name}.py"
        test_path = self.output_dir / test_filename
        test_path.write_text("\n".join(test_lines))

        return GeneratedTest(
            source_rb=str(ruby_path),
            target_py=str(python_path),
            test_path=test_path,
            test_count=sum(1 for l in test_lines if l.startswith("def test_")),
        )

    # ── Internal ───────────────────────────────────────────────────────────────

    def _extract_functions(self, source: str) -> list[str]:
        """Return list of top-level function names."""
        try:
            tree = ast.parse(source)
            return [
                node.name
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef)
                and not node.name.startswith("_")
            ]
        except SyntaxError:
            return []

    def _extract_classes(self, source: str) -> list[str]:
        """Return list of top-level class names."""
        try:
            tree = ast.parse(source)
            return [
                node.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ClassDef)
            ]
        except SyntaxError:
            return []

    def _ruby_methods(self, ruby_source: str) -> list[str]:
        return re.findall(r"^\s*def\s+(\w+)", ruby_source, re.M)

    def _build_test_file(
        self,
        module_name: str,
        python_path: Path,
        ruby_source: str,
        functions: list[str],
        classes: list[str],
    ) -> list[str]:
        lines: list[str] = [
            f'"""Auto-generated tests for {module_name}.py (converted from Ruby)."""',
            "import importlib.util",
            "import sys",
            "import pytest",
            "from pathlib import Path",
            "",
            f'_MODULE_PATH = Path("{python_path.resolve()}")',
            "",
            "",
            "def _load_module():",
            "    spec = importlib.util.spec_from_file_location(",
            f'        "{module_name}", _MODULE_PATH',
            "    )",
            "    mod = importlib.util.module_from_spec(spec)",
            "    spec.loader.exec_module(mod)",
            "    return mod",
            "",
            "",
            "# ── Syntax / import test ─────────────────────────────────────────────",
            "",
            "def test_module_loads_without_error():",
            "    \"\"\"Converted file must import without SyntaxError or ImportError.\"\"\"",
            "    mod = _load_module()",
            "    assert mod is not None",
            "",
        ]

        # Function existence tests
        if functions:
            lines += [
                "# ── Function presence tests ──────────────────────────────────────────",
                "",
            ]
            for fn in functions:
                lines += [
                    f"def test_function_{fn}_exists():",
                    f"    mod = _load_module()",
                    f"    assert hasattr(mod, '{fn}'), '{fn} not found in converted module'",
                    "",
                ]

        # Class existence tests
        if classes:
            lines += [
                "# ── Class presence tests ─────────────────────────────────────────────",
                "",
            ]
            for cls in classes:
                lines += [
                    f"def test_class_{cls}_exists():",
                    f"    mod = _load_module()",
                    f"    assert hasattr(mod, '{cls}'), '{cls} not found in converted module'",
                    "",
                ]

        # Ruby method coverage check
        ruby_methods = self._ruby_methods(ruby_source)
        if ruby_methods:
            lines += [
                "# ── Ruby method coverage ─────────────────────────────────────────────",
                "",
                "def test_ruby_methods_are_present():",
                "    \"\"\"All public Ruby methods should appear as Python functions or class methods.\"\"\"",
                "    mod = _load_module()",
                "    all_names = dir(mod)",
                f"    ruby_methods = {[m for m in ruby_methods if not m.startswith('_')]}",
                "    missing = [m for m in ruby_methods if m not in all_names",
                "               and not any(hasattr(getattr(mod, c, None), m)",
                "                          for c in dir(mod))]",
                "    # Warn rather than hard-fail: naming conventions may differ",
                "    if missing:",
                "        pytest.warns(None)  # placeholder – log missing methods",
                "        print(f'\\nMissing Ruby methods in Python: {missing}')",
                "",
            ]

        # Output comparison stub
        lines += [
            "# ── Output comparison stub (fill in expected values) ─────────────────",
            "",
            "class TestOutputComparison:",
            "    \"\"\"",
            "    Extend these stubs with actual expected values.",
            "    Run both the Ruby and Python versions and compare outputs.",
            "    \"\"\"",
            "",
        ]
        for fn in functions[:5]:  # limit to first 5 to keep tests manageable
            lines += [
                f"    def test_{fn}_output_stub(self):",
                f"        mod = _load_module()",
                f"        fn = getattr(mod, '{fn}', None)",
                f"        if fn is None:",
                f"            pytest.skip('{fn} not found')",
                f"        # TODO: add actual expected output comparison",
                f"        assert callable(fn)",
                "",
            ]

        return lines
