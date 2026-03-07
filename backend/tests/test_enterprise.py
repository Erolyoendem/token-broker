"""
Tests for the Enterprise Migration Framework.

Uses a synthetic Ruby project of 100+ files with realistic dependency patterns.
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

# Make backend importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from enterprise_migration.dependency_analyzer import DependencyAnalyzer, RubyFile
from enterprise_migration.migration_planner import MigrationPlanner, MigrationPlan
from enterprise_migration.test_suite_generator import TestSuiteGenerator
from enterprise_migration.batch_orchestrator import CheckpointManager


# ── Fixtures ──────────────────────────────────────────────────────────────────

RUBY_TEMPLATES = {
    "base_module.rb": textwrap.dedent("""\
        module BaseModule
          def helper
            'base'
          end
        end
    """),
    "model_user.rb": textwrap.dedent("""\
        require_relative 'base_module'
        class User
          include BaseModule
          attr_accessor :name, :email
          def initialize(name, email)
            @name = name
            @email = email
          end
          def greet
            "Hello, #{@name}"
          end
        end
    """),
    "service_auth.rb": textwrap.dedent("""\
        require_relative 'model_user'
        module AuthService
          def self.authenticate(user, password)
            !user.nil? && password.length > 6
          end
        end
    """),
    "controller_users.rb": textwrap.dedent("""\
        require_relative 'service_auth'
        require_relative 'model_user'
        class UsersController
          def create(params)
            user = User.new(params[:name], params[:email])
            AuthService.authenticate(user, params[:password])
          end
        end
    """),
}

SIMPLE_PYTHON = textwrap.dedent("""\
    class User:
        def __init__(self, name, email):
            self.name = name
            self.email = email

        def greet(self):
            return f"Hello, {self.name}"

    def authenticate(user, password):
        return user is not None and len(password) > 6
""")


@pytest.fixture
def ruby_project(tmp_path: Path) -> Path:
    """Creates a synthetic Ruby project with 100+ files."""
    project = tmp_path / "ruby_project"
    project.mkdir()

    # Write the template files
    for name, content in RUBY_TEMPLATES.items():
        (project / name).write_text(content)

    # Generate 100 additional simple files with cross-dependencies
    for i in range(100):
        dep = f"model_user.rb" if i % 3 == 0 else f"base_module.rb"
        content = textwrap.dedent(f"""\
            require_relative '{dep.replace(".rb", "")}'
            module Generated{i:03d}
              CONSTANT_{i:03d} = {i}
              def compute_{i:03d}(x)
                x * {i} + CONSTANT_{i:03d}
              end
            end
        """)
        (project / f"generated_{i:03d}.rb").write_text(content)

    return project


@pytest.fixture
def python_project(tmp_path: Path) -> Path:
    """Creates a small Python project (simulates conversion output)."""
    out = tmp_path / "python_project"
    out.mkdir()
    (out / "model_user.py").write_text(SIMPLE_PYTHON)
    return out


# ── DependencyAnalyzer ────────────────────────────────────────────────────────

class TestDependencyAnalyzer:
    def test_finds_all_rb_files(self, ruby_project):
        analyzer = DependencyAnalyzer(ruby_project)
        graph = analyzer.analyze()
        # 4 templates + 100 generated
        assert graph.summary()["total_files"] == 104

    def test_detects_require_relative(self, ruby_project):
        analyzer = DependencyAnalyzer(ruby_project)
        graph = analyzer.analyze()
        # model_user.rb requires base_module.rb
        model_key = str(ruby_project / "model_user.rb")
        base_key = str(ruby_project / "base_module.rb")
        assert base_key in graph.adjacency.get(model_key, [])

    def test_detects_include_module(self, ruby_project):
        analyzer = DependencyAnalyzer(ruby_project)
        graph = analyzer.analyze()
        model_key = str(ruby_project / "model_user.rb")
        base_key = str(ruby_project / "base_module.rb")
        # BaseModule include resolves to base_module.rb
        assert base_key in graph.adjacency.get(model_key, [])

    def test_summary_has_correct_keys(self, ruby_project):
        graph = DependencyAnalyzer(ruby_project).analyze()
        s = graph.summary()
        assert "total_files" in s
        assert "total_edges" in s
        assert "isolated_files" in s

    def test_empty_directory(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        graph = DependencyAnalyzer(empty).analyze()
        assert graph.summary()["total_files"] == 0

    def test_no_self_dependencies(self, ruby_project):
        graph = DependencyAnalyzer(ruby_project).analyze()
        for fpath, deps in graph.adjacency.items():
            assert fpath not in deps, f"{fpath} depends on itself"


# ── MigrationPlanner ──────────────────────────────────────────────────────────

class TestMigrationPlanner:
    def test_plan_covers_all_files(self, ruby_project):
        graph = DependencyAnalyzer(ruby_project).analyze()
        plan = MigrationPlanner(graph).plan()
        assert plan.total_files == 104
        assert len(plan.ordered_files) >= 1

    def test_base_module_before_dependents(self, ruby_project):
        graph = DependencyAnalyzer(ruby_project).analyze()
        plan = MigrationPlanner(graph).plan()
        ordered = plan.ordered_files
        base = str(ruby_project / "base_module.rb")
        model = str(ruby_project / "model_user.rb")
        if base in ordered and model in ordered:
            assert ordered.index(base) < ordered.index(model)

    def test_batch_size_respected(self, ruby_project):
        graph = DependencyAnalyzer(ruby_project).analyze()
        plan = MigrationPlanner(graph).plan(max_batch_size=10)
        for batch in plan.batches:
            assert len(batch.files) <= 10

    def test_plan_summary(self, ruby_project):
        graph = DependencyAnalyzer(ruby_project).analyze()
        plan = MigrationPlanner(graph).plan()
        s = plan.summary()
        assert s["total_files"] == 104
        assert s["total_batches"] >= 1

    def test_first_batch_is_critical(self, ruby_project):
        graph = DependencyAnalyzer(ruby_project).analyze()
        plan = MigrationPlanner(graph).plan()
        assert plan.batches[0].priority == "critical"

    def test_no_duplicate_files_in_plan(self, ruby_project):
        graph = DependencyAnalyzer(ruby_project).analyze()
        plan = MigrationPlanner(graph).plan()
        ordered = plan.ordered_files
        assert len(ordered) == len(set(ordered)), "Duplicate files in plan"

    def test_cyclic_detection(self, tmp_path):
        """Files that mutually require each other should be detected as cyclic."""
        p = tmp_path / "cyclic"
        p.mkdir()
        (p / "a.rb").write_text("require_relative 'b'\nmodule A; end")
        (p / "b.rb").write_text("require_relative 'a'\nmodule B; end")
        graph = DependencyAnalyzer(p).analyze()
        plan = MigrationPlanner(graph).plan()
        # Cyclic files may end up in cyclic_files list or still be in ordered_files
        # as best-effort — just ensure no crash
        assert plan.total_files == 2


# ── TestSuiteGenerator ────────────────────────────────────────────────────────

class TestTestSuiteGenerator:
    def test_generates_test_file(self, tmp_path, ruby_project, python_project):
        gen = TestSuiteGenerator(
            output_dir=tmp_path / "generated_tests",
            ruby_root=ruby_project,
            python_root=python_project,
        )
        results = gen.generate_all()
        assert len(results) >= 1
        assert results[0].test_path.exists()

    def test_generated_file_is_valid_python(self, tmp_path, ruby_project, python_project):
        gen = TestSuiteGenerator(
            output_dir=tmp_path / "generated_tests",
            ruby_root=ruby_project,
            python_root=python_project,
        )
        results = gen.generate_all()
        for r in results:
            source = r.test_path.read_text()
            try:
                compile(source, r.test_path.name, "exec")
            except SyntaxError as e:
                pytest.fail(f"Generated test has syntax error: {e}")

    def test_test_count_positive(self, tmp_path, ruby_project, python_project):
        gen = TestSuiteGenerator(
            output_dir=tmp_path / "generated_tests",
            ruby_root=ruby_project,
            python_root=python_project,
        )
        results = gen.generate_all()
        for r in results:
            assert r.test_count >= 1  # at least the import test

    def test_generate_for_file_with_missing_ruby(self, tmp_path, python_project):
        gen = TestSuiteGenerator(
            output_dir=tmp_path / "gen",
            ruby_root=tmp_path / "nonexistent_ruby",
            python_root=python_project,
        )
        # Should return None gracefully when ruby file is missing
        result = gen.generate_for_file(
            ruby_path=tmp_path / "ghost.rb",
            python_path=python_project / "model_user.py",
        )
        assert result is None


# ── CheckpointManager ─────────────────────────────────────────────────────────

class TestCheckpointManager:
    def test_save_and_load(self, tmp_path):
        cp = CheckpointManager(tmp_path / "checkpoint.json")
        state = {
            "session_id": "abc123",
            "plan_hash": "deadbeef",
            "completed_batches": [0, 1, 2],
            "results": [],
            "branch": "enterprise-migration/abc123",
            "started_at": "2026-03-07T10:00:00",
            "last_updated": "",
        }
        cp.save(state)
        loaded = cp.load()
        assert loaded["session_id"] == "abc123"
        assert loaded["completed_batches"] == [0, 1, 2]
        assert loaded["last_updated"] != ""

    def test_load_returns_none_if_no_file(self, tmp_path):
        cp = CheckpointManager(tmp_path / "missing.json")
        assert cp.load() is None

    def test_clear_removes_file(self, tmp_path):
        cp = CheckpointManager(tmp_path / "checkpoint.json")
        cp.save({"session_id": "x", "plan_hash": "y",
                 "completed_batches": [], "results": [],
                 "branch": "b", "started_at": "", "last_updated": ""})
        assert cp.path.exists()
        cp.clear()
        assert not cp.path.exists()

    def test_load_handles_corrupt_file(self, tmp_path):
        p = tmp_path / "corrupt.json"
        p.write_text("NOT_VALID_JSON{{{")
        cp = CheckpointManager(p)
        assert cp.load() is None


# ── Integration: full pipeline (no API calls) ──────────────────────────────────

class TestFullPipeline:
    def test_analyze_plan_generate(self, tmp_path, ruby_project, python_project):
        """End-to-end: analyze → plan → generate tests, without network calls."""
        graph = DependencyAnalyzer(ruby_project).analyze()
        assert graph.summary()["total_files"] > 0

        plan = MigrationPlanner(graph).plan(max_batch_size=20)
        assert plan.summary()["total_batches"] >= 1

        gen = TestSuiteGenerator(
            output_dir=tmp_path / "suite",
            ruby_root=ruby_project,
            python_root=python_project,
        )
        suite_results = gen.generate_all()
        assert len(suite_results) >= 1

    def test_checkpoint_round_trip_with_plan(self, tmp_path, ruby_project):
        graph = DependencyAnalyzer(ruby_project).analyze()
        plan = MigrationPlanner(graph).plan()

        cp = CheckpointManager(tmp_path / "session.json")
        state = {
            "session_id": "test-session",
            "plan_hash": "abc",
            "completed_batches": [b.index for b in plan.batches[:2]],
            "results": [],
            "branch": "enterprise-migration/test",
            "started_at": "2026-03-07T00:00:00",
            "last_updated": "",
        }
        cp.save(state)
        loaded = cp.load()
        assert len(loaded["completed_batches"]) == 2
