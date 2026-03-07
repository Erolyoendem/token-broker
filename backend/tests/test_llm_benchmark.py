"""
Tests for the LLM Benchmark Framework.

All external dependencies (HTTP calls, Supabase) are mocked.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from llm_benchmark.matrix import BenchmarkMatrix, MatrixBuilder, ProviderScore
from llm_benchmark.runner import BenchmarkRun, BenchmarkRunner, RunResult
from llm_benchmark.store import BenchmarkStore
from llm_benchmark.tasks import (
    CATEGORIES,
    TASKS,
    BenchmarkTask,
    _expect_number,
    _expect_keywords,
    _non_empty_creative,
    _valid_python_syntax,
    get_task,
    tasks_by_category,
)


# ── Task Tests ────────────────────────────────────────────────────────────────

class TestTaskValidators:
    def test_expect_number_pass(self):
        validate = _expect_number("391")
        ok, _ = validate("The answer is 391.")
        assert ok is True

    def test_expect_number_fail(self):
        validate = _expect_number("391")
        ok, _ = validate("The answer is 390.")
        assert ok is False

    def test_expect_number_float(self):
        validate = _expect_number("80")
        ok, _ = validate("The speed is 80.0 km/h.")
        assert ok is True

    def test_expect_keywords_pass(self):
        validate = _expect_keywords("paris")
        ok, _ = validate("The capital of France is Paris.")
        assert ok is True

    def test_expect_keywords_case_insensitive(self):
        validate = _expect_keywords("attention", "transformer")
        ok, _ = validate("The Transformer architecture uses Attention mechanisms.")
        assert ok is True

    def test_expect_keywords_missing(self):
        validate = _expect_keywords("attention", "transformer")
        ok, note = validate("It uses neural networks.")
        assert ok is False
        assert "attention" in note or "transformer" in note

    def test_creative_min_words_pass(self):
        validate = _non_empty_creative(min_words=5)
        ok, _ = validate("one two three four five")
        assert ok is True

    def test_creative_min_words_fail(self):
        validate = _non_empty_creative(min_words=10)
        ok, _ = validate("too short")
        assert ok is False

    def test_valid_python_syntax_pass(self):
        ok, note = _valid_python_syntax("def foo(x):\n    return x * 2\n")
        assert ok is True
        assert "ok" in note

    def test_valid_python_syntax_fail(self):
        ok, note = _valid_python_syntax("def foo(\n  # unterminated")
        assert ok is False

    def test_valid_python_syntax_strips_fences(self):
        ok, _ = _valid_python_syntax("```python\nprint('hi')\n```")
        assert ok is True


class TestTaskCatalogue:
    def test_all_tasks_have_unique_ids(self):
        ids = [t.id for t in TASKS]
        assert len(ids) == len(set(ids)), "Duplicate task IDs"

    def test_all_tasks_have_category(self):
        for t in TASKS:
            assert t.category in CATEGORIES, f"{t.id} has unknown category {t.category}"

    def test_get_task_known(self):
        task = get_task("math_001")
        assert isinstance(task, BenchmarkTask)
        assert task.id == "math_001"

    def test_get_task_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown task"):
            get_task("nonexistent_999")

    def test_tasks_by_category_math(self):
        math_tasks = tasks_by_category("math")
        assert len(math_tasks) >= 3
        assert all(t.category == "math" for t in math_tasks)

    def test_tasks_by_category_code_gen(self):
        code_tasks = tasks_by_category("code_gen")
        assert len(code_tasks) >= 2

    def test_math_001_validator_correct(self):
        task = get_task("math_001")
        ok, _ = task.validate("The result is 391")
        assert ok is True

    def test_math_001_validator_wrong(self):
        task = get_task("math_001")
        ok, _ = task.validate("The result is 392")
        assert ok is False

    def test_factual_001_validates_paris(self):
        task = get_task("factual_001")
        ok, _ = task.validate("Paris")
        assert ok is True

    def test_code_001_validates_syntax(self):
        task = get_task("code_001")
        code = "def fibonacci(n):\n    if n <= 1:\n        return n\n    return fibonacci(n-1) + fibonacci(n-2)\n"
        ok, _ = task.validate(code)
        assert ok is True


# ── Runner Tests (mocked HTTP) ────────────────────────────────────────────────

class TestBenchmarkRunner:
    def _make_runner(self, response: str = "42", tokens: int = 50) -> BenchmarkRunner:
        runner = BenchmarkRunner(proxy_url="http://mock", api_key="test", providers=["test_prov"])
        runner._call = MagicMock(return_value=(response, tokens))
        return runner

    def test_run_task_pass(self):
        runner = self._make_runner(response="The answer is 391")
        task = get_task("math_001")
        result = runner.run_task(task, "test_prov")
        assert result.passed is True
        assert result.tokens_used == 50
        assert result.provider == "test_prov"
        assert result.latency_s >= 0

    def test_run_task_fail(self):
        runner = self._make_runner(response="I don't know")
        task = get_task("math_001")
        result = runner.run_task(task, "test_prov")
        assert result.passed is False

    def test_run_task_records_error_on_exception(self):
        runner = BenchmarkRunner(proxy_url="http://mock", api_key="test", providers=["bad"])
        runner._call = MagicMock(side_effect=RuntimeError("timeout"))
        task = get_task("math_001")
        result = runner.run_task(task, "bad")
        assert result.error != ""
        assert result.passed is False

    def test_run_all_returns_one_run_per_provider(self):
        runner = BenchmarkRunner(
            proxy_url="http://mock", api_key="test",
            providers=["p1", "p2"],
        )
        runner._call = MagicMock(return_value=("391", 10))
        runs = runner.run_all(task_ids=["math_001"])
        assert len(runs) == 2
        assert {r.provider for r in runs} == {"p1", "p2"}

    def test_benchmark_run_accuracy(self):
        run = BenchmarkRun(provider="test")
        run.results = [
            RunResult("t1", "math", "test", True,  "391", "ok", 1.0, 10),
            RunResult("t2", "math", "test", False, "bad", "x",  1.0, 10),
            RunResult("t3", "math", "test", True,  "391", "ok", 1.0, 10),
        ]
        assert run.accuracy == pytest.approx(2 / 3)

    def test_benchmark_run_avg_latency(self):
        run = BenchmarkRun(provider="test")
        run.results = [
            RunResult("t1", "math", "test", True, "ok", "ok", 2.0, 10),
            RunResult("t2", "math", "test", True, "ok", "ok", 4.0, 10),
        ]
        assert run.avg_latency == pytest.approx(3.0)

    def test_benchmark_run_total_tokens(self):
        run = BenchmarkRun(provider="test")
        run.results = [
            RunResult("t1", "math", "test", True, "ok", "ok", 1.0, 100),
            RunResult("t2", "math", "test", True, "ok", "ok", 1.0, 200),
        ]
        assert run.total_tokens == 300


# ── Matrix Tests ──────────────────────────────────────────────────────────────

class TestMatrixBuilder:
    def _make_run(self, provider: str, accuracy_frac: float, latency: float) -> BenchmarkRun:
        run = BenchmarkRun(provider=provider)
        n = 10
        for i in range(n):
            passed = i < int(n * accuracy_frac)
            run.results.append(RunResult(
                f"t{i}", "math", provider, passed, "ok", "ok", latency, 50
            ))
        return run

    def test_build_returns_matrix(self):
        runs = [self._make_run("nvidia", 0.9, 1.5)]
        matrix = MatrixBuilder().build(runs)
        assert isinstance(matrix, BenchmarkMatrix)
        assert len(matrix.providers) == 1

    def test_best_provider_ranked_first(self):
        runs = [
            self._make_run("bad_prov",  0.3, 5.0),
            self._make_run("good_prov", 0.9, 1.0),
        ]
        matrix = MatrixBuilder().build(runs)
        assert matrix.providers[0].provider == "good_prov"

    def test_empty_runs_returns_empty_matrix(self):
        matrix = MatrixBuilder().build([])
        assert matrix.providers == []

    def test_composite_score_between_0_and_1(self):
        runs = [self._make_run("nvidia", 0.8, 2.0)]
        matrix = MatrixBuilder().build(runs)
        score = matrix.providers[0].composite_score
        assert 0.0 <= score <= 1.0

    def test_best_for_accuracy(self):
        runs = [
            self._make_run("fast_cheap", 0.5, 0.5),
            self._make_run("accurate",   0.95, 3.0),
        ]
        matrix = MatrixBuilder().build(runs)
        best = matrix.best_for("accuracy")
        assert best is not None
        assert best.provider == "accurate"

    def test_as_dict_structure(self):
        runs = [self._make_run("nvidia", 0.8, 2.0)]
        d = MatrixBuilder().build(runs).as_dict()
        assert "providers" in d
        assert "generated_at" in d
        p = d["providers"][0]
        assert "provider" in p
        assert "overall_accuracy" in p
        assert "composite_score" in p
        assert "by_category" in p


# ── Store Tests (mocked Supabase) ─────────────────────────────────────────────

class TestBenchmarkStore:
    def _make_store(self, rows: list[dict] | None = None) -> BenchmarkStore:
        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.limit.return_value \
            .execute.return_value.data = rows or []
        mock_db.table.return_value.insert.return_value.execute.return_value.data = [{"id": 1}]
        # chain for latest_results
        mock_db.table.return_value.select.return_value.order.return_value \
            .limit.return_value.execute.return_value.data = rows or []
        mock_db.table.return_value.select.return_value.order.return_value \
            .limit.return_value.eq.return_value.execute.return_value.data = rows or []
        return BenchmarkStore(db_client=mock_db)

    def test_ensure_table_ok(self):
        store = self._make_store()
        assert store.ensure_table() is True

    def test_ensure_table_fail(self):
        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.limit.return_value \
            .execute.side_effect = Exception("table not found")
        store = BenchmarkStore(db_client=mock_db)
        assert store.ensure_table() is False

    def test_insert_result_calls_db(self):
        store = self._make_store()
        result = store.insert_result(
            "math_001", "math", "nvidia", True, "391", "ok", 1.2, 50
        )
        assert result is not None
        store._db.table.assert_called_with("benchmark_results")

    def test_provider_summary_empty(self):
        store = self._make_store(rows=[])
        summary = store.provider_summary()
        assert summary == []

    def test_provider_summary_aggregates(self):
        rows = [
            {"provider": "nvidia", "passed": True,  "latency_s": 1.0},
            {"provider": "nvidia", "passed": True,  "latency_s": 3.0},
            {"provider": "nvidia", "passed": False, "latency_s": 2.0},
        ]
        store = self._make_store(rows=rows)
        summary = store.provider_summary()
        nvidia = next((s for s in summary if s["provider"] == "nvidia"), None)
        assert nvidia is not None
        assert nvidia["tasks_run"] == 3
        assert nvidia["tasks_passed"] == 2
        assert nvidia["accuracy"] == pytest.approx(2 / 3, rel=1e-2)
