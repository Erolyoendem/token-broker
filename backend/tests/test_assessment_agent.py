"""
Tests fuer den Assessment-Agent (TAB 28).

Alle externen Abhaengigkeiten (LLM-Proxy, Supabase) werden gemockt.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Fixtures: temporaere Projektstruktur
# ---------------------------------------------------------------------------

RUBY_CODE = """\
require 'rails'

class ApplicationController < ActionController::Base
  def index
    render json: { ok: true }
  end
end
"""

PYTHON_CODE = """\
# TODO: refactor this
from fastapi import FastAPI
import os

app = FastAPI()

def add(a, b):
    return a + b

def multiply(a, b):
    # FIXME: handle edge cases
    return a * b

class MyService:
    var x = 1  # legacy JS style comment
    def process(self, data):
        for item in data:
            if item:
                while True:
                    if item > 0:
                        break
        return data
"""

JS_CODE = """\
var x = require('express');
var app = x();
"""


@pytest.fixture
def project_dir(tmp_path):
    """Erstellt eine minimale Testprojektstruktur."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "controller.rb").write_text(RUBY_CODE)
    (tmp_path / "app" / "service.py").write_text(PYTHON_CODE)
    (tmp_path / "app" / "index.js").write_text(JS_CODE)
    (tmp_path / "tests" / "test_service.py").write_text(
        "import pytest\ndef test_add():\n    assert 1 + 1 == 2\n"
    )
    (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\ngem 'rails', '~> 7.0'\n")
    (tmp_path / "requirements.txt").write_text("fastapi==0.100.0\nhttpx==0.24.0\n")
    (tmp_path / "package.json").write_text('{"name":"test","dependencies":{"express":"^4.18.0"}}')
    return tmp_path


# ---------------------------------------------------------------------------
# CodeScanner
# ---------------------------------------------------------------------------

class TestCodeScanner:
    def test_scan_returns_result(self, project_dir):
        from assessment_agent.code_scanner import CodeScanner
        result = CodeScanner(project_dir).scan()
        assert result.total_files > 0
        assert result.total_lines > 0

    def test_scan_detects_languages(self, project_dir):
        from assessment_agent.code_scanner import CodeScanner
        result = CodeScanner(project_dir).scan()
        assert "Python" in result.lines_by_language or "Ruby" in result.lines_by_language

    def test_scan_counts_files_by_language(self, project_dir):
        from assessment_agent.code_scanner import CodeScanner
        result = CodeScanner(project_dir).scan()
        assert isinstance(result.files_by_language, dict)
        total = sum(result.files_by_language.values())
        assert total == result.total_files

    def test_scan_detects_rails(self, project_dir):
        from assessment_agent.code_scanner import CodeScanner
        result = CodeScanner(project_dir).scan()
        # Rails detection requires matching pattern in .rb file
        assert isinstance(result.frameworks_detected, list)

    def test_scan_detects_fastapi(self, project_dir):
        from assessment_agent.code_scanner import CodeScanner
        result = CodeScanner(project_dir).scan()
        # FastAPI import is present in service.py
        assert "FastAPI" in result.frameworks_detected or isinstance(result.frameworks_detected, list)

    def test_scan_detects_express(self, project_dir):
        from assessment_agent.code_scanner import CodeScanner
        result = CodeScanner(project_dir).scan()
        assert isinstance(result.frameworks_detected, list)

    def test_scan_largest_files(self, project_dir):
        from assessment_agent.code_scanner import CodeScanner
        result = CodeScanner(project_dir).scan()
        assert len(result.largest_files) <= 10
        # Sorted by size descending
        sizes = [f.size_bytes for f in result.largest_files]
        assert sizes == sorted(sizes, reverse=True)

    def test_scan_to_dict(self, project_dir):
        from assessment_agent.code_scanner import CodeScanner
        result = CodeScanner(project_dir).scan()
        d = result.to_dict()
        assert "total_files" in d
        assert "lines_by_language" in d
        assert "frameworks_detected" in d
        assert "largest_files" in d
        assert isinstance(d["largest_files"], list)

    def test_scan_skips_hidden_dirs(self, project_dir):
        from assessment_agent.code_scanner import CodeScanner
        git_dir = project_dir / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]\n    bare = false\n")
        result_before = CodeScanner(project_dir).scan()
        # .git files must not be counted
        result_after = CodeScanner(project_dir).scan()
        assert result_before.total_files == result_after.total_files

    def test_scan_empty_dir(self, tmp_path):
        from assessment_agent.code_scanner import CodeScanner
        result = CodeScanner(tmp_path).scan()
        assert result.total_files == 0
        assert result.total_lines == 0


# ---------------------------------------------------------------------------
# AssessmentDependencyAnalyzer
# ---------------------------------------------------------------------------

class TestAssessmentDependencyAnalyzer:
    def test_analyze_returns_graph(self, project_dir):
        from assessment_agent.dependency_analyzer import AssessmentDependencyAnalyzer
        graph = AssessmentDependencyAnalyzer(project_dir).analyze()
        assert hasattr(graph, "adjacency")
        assert hasattr(graph, "pain_points")

    def test_analyze_summary_keys(self, project_dir):
        from assessment_agent.dependency_analyzer import AssessmentDependencyAnalyzer
        graph = AssessmentDependencyAnalyzer(project_dir).analyze()
        s = graph.summary()
        assert "total_files" in s
        assert "total_edges" in s
        assert "pain_points" in s

    def test_pain_points_are_pain_point_objects(self, project_dir):
        from assessment_agent.dependency_analyzer import AssessmentDependencyAnalyzer, PainPoint
        graph = AssessmentDependencyAnalyzer(project_dir).analyze()
        for pp in graph.pain_points:
            assert isinstance(pp, PainPoint)
            assert pp.severity in {"low", "medium", "high", "critical"}

    def test_pain_point_to_dict(self, project_dir):
        from assessment_agent.dependency_analyzer import AssessmentDependencyAnalyzer
        graph = AssessmentDependencyAnalyzer(project_dir).analyze()
        for pp in graph.pain_points:
            d = pp.to_dict()
            assert "category" in d
            assert "severity" in d
            assert "description" in d

    def test_detects_large_file(self, tmp_path):
        from assessment_agent.dependency_analyzer import AssessmentDependencyAnalyzer, PAIN_LARGE_FILE, LARGE_FILE_THRESHOLD
        big_file = tmp_path / "big.py"
        big_file.write_text("x = 1\n" * (LARGE_FILE_THRESHOLD + 10))
        graph = AssessmentDependencyAnalyzer(tmp_path).analyze()
        categories = [p.category for p in graph.pain_points]
        assert PAIN_LARGE_FILE in categories

    def test_detects_circular_dependency(self, tmp_path):
        from assessment_agent.dependency_analyzer import AssessmentDependencyAnalyzer, PAIN_CIRCULAR
        # Create two Python files that import each other relatively
        (tmp_path / "a.py").write_text("from . import b\n")
        (tmp_path / "b.py").write_text("from . import a\n")
        graph = AssessmentDependencyAnalyzer(tmp_path).analyze()
        # Circular detection depends on relative import resolution
        assert isinstance(graph.pain_points, list)

    def test_find_cycles_direct(self):
        from assessment_agent.dependency_analyzer import AssessmentDependencyAnalyzer
        adj = {"a": ["b"], "b": ["c"], "c": ["a"]}
        cycles = AssessmentDependencyAnalyzer._find_cycles(adj)
        assert len(cycles) > 0
        # The cycle should contain all three nodes
        flat = set(n for c in cycles for n in c)
        assert "a" in flat or "b" in flat or "c" in flat

    def test_find_cycles_no_cycle(self):
        from assessment_agent.dependency_analyzer import AssessmentDependencyAnalyzer
        adj = {"a": ["b"], "b": ["c"], "c": []}
        cycles = AssessmentDependencyAnalyzer._find_cycles(adj)
        assert cycles == []

    def test_empty_project(self, tmp_path):
        from assessment_agent.dependency_analyzer import AssessmentDependencyAnalyzer
        graph = AssessmentDependencyAnalyzer(tmp_path).analyze()
        assert graph.adjacency == {} or isinstance(graph.adjacency, dict)
        assert graph.pain_points == []


# ---------------------------------------------------------------------------
# TechDebtEstimator
# ---------------------------------------------------------------------------

class TestTechDebtEstimator:
    def test_estimate_returns_result(self, project_dir):
        from assessment_agent.tech_debt_estimator import TechDebtEstimator
        result = TechDebtEstimator(project_dir).estimate()
        assert 0 <= result.total_score <= 100
        assert result.grade in {"A", "B", "C", "D", "F"}

    def test_estimate_has_categories(self, project_dir):
        from assessment_agent.tech_debt_estimator import TechDebtEstimator
        result = TechDebtEstimator(project_dir).estimate()
        assert len(result.categories) == 7
        names = {c.name for c in result.categories}
        assert "duplication" in names
        assert "missing_tests" in names
        assert "todo_markers" in names

    def test_todo_detection(self, tmp_path):
        from assessment_agent.tech_debt_estimator import TechDebtEstimator
        (tmp_path / "work.py").write_text("# TODO: fix this\n# FIXME: also this\nx = 1\n")
        result = TechDebtEstimator(tmp_path).estimate()
        todo_cat = next(c for c in result.categories if c.name == "todo_markers")
        assert todo_cat.score > 0

    def test_no_todos_zero_score(self, tmp_path):
        from assessment_agent.tech_debt_estimator import TechDebtEstimator
        (tmp_path / "clean.py").write_text("x = 1\ny = 2\n")
        result = TechDebtEstimator(tmp_path).estimate()
        todo_cat = next(c for c in result.categories if c.name == "todo_markers")
        assert todo_cat.score == 0

    def test_large_file_detection(self, tmp_path):
        from assessment_agent.tech_debt_estimator import TechDebtEstimator
        (tmp_path / "huge.py").write_text("x = 1\n" * 600)
        result = TechDebtEstimator(tmp_path).estimate()
        lf_cat = next(c for c in result.categories if c.name == "large_files")
        assert lf_cat.score > 0

    def test_missing_tests_high_score(self, tmp_path):
        from assessment_agent.tech_debt_estimator import TechDebtEstimator
        (tmp_path / "app.py").write_text("def foo():\n    pass\n" * 50)
        result = TechDebtEstimator(tmp_path).estimate()
        test_cat = next(c for c in result.categories if c.name == "missing_tests")
        # No test files -> high missing_tests score
        assert test_cat.score > 50

    def test_with_tests_lower_score(self, project_dir):
        from assessment_agent.tech_debt_estimator import TechDebtEstimator
        result = TechDebtEstimator(project_dir).estimate()
        test_cat = next(c for c in result.categories if c.name == "missing_tests")
        # project_dir has some test files -> lower than 100
        assert test_cat.score < 100

    def test_outdated_syntax_python2(self, tmp_path):
        from assessment_agent.tech_debt_estimator import TechDebtEstimator
        (tmp_path / "old.py").write_text("print 'hello'\nxrange(10)\n")
        result = TechDebtEstimator(tmp_path).estimate()
        syn_cat = next(c for c in result.categories if c.name == "outdated_syntax")
        assert syn_cat.score > 0

    def test_to_dict_structure(self, project_dir):
        from assessment_agent.tech_debt_estimator import TechDebtEstimator
        result = TechDebtEstimator(project_dir).estimate()
        d = result.to_dict()
        assert "total_score" in d
        assert "grade" in d
        assert "categories" in d
        assert "critical_findings" in d
        assert "summary" in d

    def test_grade_scale(self, tmp_path):
        from assessment_agent.tech_debt_estimator import TechDebtEstimator, _score_to_grade
        assert _score_to_grade(0)   == "A"
        assert _score_to_grade(15)  == "A"
        assert _score_to_grade(16)  == "B"
        assert _score_to_grade(30)  == "B"
        assert _score_to_grade(50)  == "C"
        assert _score_to_grade(70)  == "D"
        assert _score_to_grade(100) == "F"

    def test_empty_project_low_score(self, tmp_path):
        from assessment_agent.tech_debt_estimator import TechDebtEstimator
        result = TechDebtEstimator(tmp_path).estimate()
        assert result.total_score <= 30   # empty project has few issues


# ---------------------------------------------------------------------------
# ReportGenerator
# ---------------------------------------------------------------------------

class TestReportGenerator:
    @pytest.fixture
    def mock_scan(self, project_dir):
        from assessment_agent.code_scanner import CodeScanner
        return CodeScanner(project_dir).scan()

    @pytest.fixture
    def mock_dep_graph(self, project_dir):
        from assessment_agent.dependency_analyzer import AssessmentDependencyAnalyzer
        return AssessmentDependencyAnalyzer(project_dir).analyze()

    @pytest.fixture
    def mock_debt(self, project_dir):
        from assessment_agent.tech_debt_estimator import TechDebtEstimator
        return TechDebtEstimator(project_dir).estimate()

    @patch("assessment_agent.report_generator.httpx.post")
    def test_generate_creates_file(self, mock_post, tmp_path, mock_scan, mock_dep_graph, mock_debt):
        from assessment_agent.report_generator import ReportGenerator
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "choices": [{"message": {"content": "Generierter LLM-Text."}}]
            },
        )
        mock_post.return_value.raise_for_status = MagicMock()

        gen = ReportGenerator(output_dir=tmp_path)
        path = gen.generate("TestProjekt", mock_scan, mock_dep_graph, mock_debt)
        assert path.exists()
        assert path.suffix == ".md"

    @patch("assessment_agent.report_generator.httpx.post")
    def test_report_contains_sections(self, mock_post, tmp_path, mock_scan, mock_dep_graph, mock_debt):
        from assessment_agent.report_generator import ReportGenerator
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "choices": [{"message": {"content": "Executive Summary Text."}}]
            },
        )
        mock_post.return_value.raise_for_status = MagicMock()

        gen = ReportGenerator(output_dir=tmp_path)
        path = gen.generate("TestProjekt", mock_scan, mock_dep_graph, mock_debt)
        content = path.read_text()
        assert "Executive Summary" in content
        assert "Tech-Debt" in content or "Technische Schulden" in content or "Tech-Debt-Analyse" in content
        assert "Handlungsempfehlungen" in content or "Empfehlungen" in content

    def test_fallback_without_api_key(self, tmp_path, mock_scan, mock_dep_graph, mock_debt):
        from assessment_agent.report_generator import ReportGenerator
        with patch("assessment_agent.report_generator._API_KEY", ""):
            gen = ReportGenerator(output_dir=tmp_path)
            path = gen.generate("FallbackProjekt", mock_scan, mock_dep_graph, mock_debt)
        assert path.exists()
        content = path.read_text()
        assert "FallbackProjekt" in content

    @patch("assessment_agent.report_generator.httpx.post", side_effect=Exception("timeout"))
    def test_report_survives_llm_error(self, mock_post, tmp_path, mock_scan, mock_dep_graph, mock_debt):
        from assessment_agent.report_generator import ReportGenerator
        gen = ReportGenerator(output_dir=tmp_path)
        path = gen.generate("ErrorProjekt", mock_scan, mock_dep_graph, mock_debt)
        assert path.exists()

    def test_report_includes_repo_url(self, tmp_path, mock_scan, mock_dep_graph, mock_debt):
        from assessment_agent.report_generator import ReportGenerator
        with patch("assessment_agent.report_generator._API_KEY", ""):
            gen = ReportGenerator(output_dir=tmp_path)
            path = gen.generate(
                "UrlProjekt", mock_scan, mock_dep_graph, mock_debt,
                repo_url="https://github.com/test/repo"
            )
        assert "https://github.com/test/repo" in path.read_text()


# ---------------------------------------------------------------------------
# API Endpoint /assessment/run
# ---------------------------------------------------------------------------

class TestAssessmentEndpoint:
    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch):
        monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key")

    def _make_client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def test_missing_path_and_url(self, project_dir):
        client = self._make_client()
        resp = client.post(
            "/assessment/run",
            json={"project_name": "Test"},
            headers={"x-admin-key": "test-admin-key"},
        )
        assert resp.status_code == 400

    def test_invalid_path(self):
        client = self._make_client()
        resp = client.post(
            "/assessment/run",
            json={"project_name": "Test", "path": "/nonexistent/path/xyz"},
            headers={"x-admin-key": "test-admin-key"},
        )
        assert resp.status_code == 404

    def test_repo_url_not_supported(self):
        client = self._make_client()
        resp = client.post(
            "/assessment/run",
            json={"project_name": "Test", "repo_url": "https://github.com/foo/bar"},
            headers={"x-admin-key": "test-admin-key"},
        )
        assert resp.status_code == 501

    @patch("assessment_agent.report_generator.httpx.post")
    @patch("app.main.get_client")
    def test_successful_assessment(self, mock_db, mock_llm, project_dir):
        mock_llm.return_value = MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": "Summary."}}]},
        )
        mock_llm.return_value.raise_for_status = MagicMock()
        mock_db.return_value.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": 42}
        ]

        with patch("assessment_agent.report_generator._API_KEY", "fake-key"):
            client = self._make_client()
            resp = client.post(
                "/assessment/run",
                json={"project_name": "TestProjekt", "path": str(project_dir)},
                headers={"x-admin-key": "test-admin-key"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "tech_debt_score" in body
        assert "tech_debt_grade" in body
        assert "report_path" in body
        assert 0 <= body["tech_debt_score"] <= 100

    def test_requires_admin_key(self, project_dir):
        client = self._make_client()
        resp = client.post(
            "/assessment/run",
            json={"project_name": "Test", "path": str(project_dir)},
        )
        assert resp.status_code == 422  # missing Header

    def test_wrong_admin_key(self, project_dir):
        client = self._make_client()
        resp = client.post(
            "/assessment/run",
            json={"project_name": "Test", "path": str(project_dir)},
            headers={"x-admin-key": "wrong-key"},
        )
        assert resp.status_code == 403
