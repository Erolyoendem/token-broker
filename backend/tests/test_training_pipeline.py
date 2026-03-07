"""
Tests for the multi-language training data pipeline.

Uses mocks for external dependencies (GitHub API, LLM, Supabase)
so tests run without any network access or credentials.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from training_data.crawler import CrawlerConfig, GitHubCrawler
from training_data.dataset import DatasetManager, TrainingPair
from training_data.language_pairs import (
    JavaScriptToTypeScript,
    PythonToJava,
    RubyToPython,
    get_pair,
)
from training_data.quality_filter import MultiAgentFilter, Rating
from training_data.synthesizer import Synthesizer, SynthesisResult
from training_data.validator import Validator


# ── Fixtures ─────────────────────────────────────────────────────────────────

RUBY_SAMPLE = """
class Greeter
  def initialize(name)
    @name = name
  end
  def greet
    puts "Hello, #{@name}!"
  end
end
"""

PYTHON_SAMPLE = """
class Greeter:
    def __init__(self, name: str) -> None:
        self.name = name
    def greet(self) -> None:
        print(f"Hello, {self.name}!")
"""

JS_SAMPLE = """
function add(a, b) {
  return a + b;
}
const result = add(1, 2);
console.log(result);
"""

TS_SAMPLE = """
function add(a: number, b: number): number {
  return a + b;
}
const result: number = add(1, 2);
console.log(result);
"""


# ── Language Pair Tests ───────────────────────────────────────────────────────

class TestRubyToPython:
    def setup_method(self):
        self.pair = RubyToPython()

    def test_pair_id(self):
        assert self.pair.pair_id == "ruby->python"

    def test_parse_detects_class(self):
        result = self.pair.parse(RUBY_SAMPLE)
        assert "class" in result.constructs
        assert result.language == "ruby"

    def test_parse_detects_method(self):
        result = self.pair.parse(RUBY_SAMPLE)
        assert "method" in result.constructs

    def test_build_prompt_contains_source(self):
        prompt = self.pair.build_prompt(RUBY_SAMPLE)
        assert RUBY_SAMPLE in prompt
        assert "Python" in prompt

    def test_validate_valid_python(self):
        result = self.pair.validate(PYTHON_SAMPLE)
        assert result.ok is True
        assert result.errors == []

    def test_validate_invalid_python(self):
        result = self.pair.validate("def foo(\n  # unterminated")
        assert result.ok is False
        assert result.errors

    def test_validate_warns_on_puts(self):
        result = self.pair.validate("puts 'hello'")
        assert any("puts" in w for w in result.warnings)

    def test_validate_warns_on_require(self):
        result = self.pair.validate("require 'json'")
        assert any("require" in w for w in result.warnings)

    def test_clean_llm_output_strips_fences(self):
        raw = "```python\nprint('hi')\n```"
        assert self.pair.clean_llm_output(raw) == "print('hi')"


class TestPythonToJava:
    def setup_method(self):
        self.pair = PythonToJava()

    def test_pair_id(self):
        assert self.pair.pair_id == "python->java"

    def test_parse_detects_class(self):
        result = self.pair.parse(PYTHON_SAMPLE)
        assert "class" in result.constructs

    def test_validate_ok_for_java_class(self):
        java_code = "public class Main { public static void main(String[] args) {} }"
        result = self.pair.validate(java_code)
        assert result.ok is True

    def test_validate_error_no_class(self):
        result = self.pair.validate("int x = 5;")
        assert result.ok is False

    def test_validate_error_unbalanced_braces(self):
        result = self.pair.validate("class Foo { void bar() {")
        assert result.ok is False


class TestJavaScriptToTypeScript:
    def setup_method(self):
        self.pair = JavaScriptToTypeScript()

    def test_pair_id(self):
        assert self.pair.pair_id == "javascript->typescript"

    def test_parse_detects_arrow(self):
        code = "const fn = (x) => { return x; };"
        result = self.pair.parse(code)
        assert "arrow_fn" in result.constructs

    def test_validate_warns_on_var(self):
        result = self.pair.validate("var x = 5;")
        assert any("var" in w for w in result.warnings)

    def test_validate_warns_no_types(self):
        result = self.pair.validate("function foo(x) { return x; }")
        assert any("type" in w.lower() for w in result.warnings)

    def test_validate_ok_with_types(self):
        result = self.pair.validate(TS_SAMPLE)
        assert result.ok is True
        assert not result.warnings  # clean TS has no warnings


class TestLanguagePairRegistry:
    def test_get_pair_ruby_python(self):
        pair = get_pair("ruby->python")
        assert isinstance(pair, RubyToPython)

    def test_get_pair_python_java(self):
        pair = get_pair("python->java")
        assert isinstance(pair, PythonToJava)

    def test_get_pair_js_ts(self):
        pair = get_pair("javascript->typescript")
        assert isinstance(pair, JavaScriptToTypeScript)

    def test_get_pair_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown language pair"):
            get_pair("cobol->brainfuck")


# ── Validator Tests ───────────────────────────────────────────────────────────

class TestValidator:
    def setup_method(self):
        self.validator = Validator()
        self.pair = RubyToPython()

    def test_valid_pair_high_confidence(self):
        score = self.validator.validate_pair(RUBY_SAMPLE, PYTHON_SAMPLE, self.pair)
        assert score.syntax_ok is True
        assert score.confidence >= 0.7

    def test_empty_target_low_confidence(self):
        score = self.validator.validate_pair(RUBY_SAMPLE, "", self.pair)
        assert score.confidence < 0.5

    def test_invalid_syntax_rejected(self):
        score = self.validator.validate_pair(RUBY_SAMPLE, "def foo(\n  # broken", self.pair)
        assert score.syntax_ok is False
        assert score.confidence < 0.6

    def test_requires_review_when_low_confidence(self):
        score = self.validator.validate_pair(RUBY_SAMPLE, "", self.pair)
        assert score.requires_review is True

    def test_no_review_needed_for_good_pair(self):
        score = self.validator.validate_pair(RUBY_SAMPLE, PYTHON_SAMPLE, self.pair)
        assert score.requires_review is False


# ── Synthesizer Tests (mocked) ────────────────────────────────────────────────

class TestSynthesizer:
    def _make_synthesizer(self, response_content: str, tokens: int = 100) -> Synthesizer:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": response_content}}],
            "usage": {"total_tokens": tokens},
            "provider": "deepseek",
        }
        mock_resp.raise_for_status = MagicMock()

        synth = Synthesizer(proxy_url="http://mock", api_key="test")
        synth._call_llm = MagicMock(return_value=(response_content, tokens, "deepseek"))
        return synth

    def test_synthesize_returns_result(self):
        synth = self._make_synthesizer(PYTHON_SAMPLE, tokens=150)
        pair = RubyToPython()
        result = synth.synthesize(RUBY_SAMPLE, pair)
        assert result.pair_id == "ruby->python"
        assert result.tokens_used == 150
        assert result.provider == "deepseek"

    def test_synthesize_strips_fences(self):
        raw = "```python\nprint('hi')\n```"
        synth = self._make_synthesizer(raw)
        pair = RubyToPython()
        result = synth.synthesize("puts 'hi'", pair)
        assert result.target_code == "print('hi')"


# ── MultiAgentFilter Tests (mocked) ──────────────────────────────────────────

class TestMultiAgentFilter:
    def _make_filter(self, ratings: list[int]) -> MultiAgentFilter:
        """Create filter whose agents return the given ratings in order."""
        responses = [f"RATING: {r}\nRATIONALE: mock evaluation" for r in ratings]
        call_count = [-1]

        async def mock_llm(system, user):
            call_count[0] += 1
            return responses[call_count[0] % len(responses)]

        f = MultiAgentFilter(proxy_url="http://mock", api_key="test")
        f._llm_call = mock_llm
        return f

    def test_consensus_accepted_on_majority_good(self):
        f = self._make_filter([4, 4, 3])
        result = f.evaluate_sync(RUBY_SAMPLE, PYTHON_SAMPLE, "ruby->python")
        assert result.accepted is True
        assert result.requires_human is False

    def test_consensus_rejected_on_majority_poor(self):
        f = self._make_filter([1, 1, 3])
        result = f.evaluate_sync(RUBY_SAMPLE, "broken code", "ruby->python")
        assert result.accepted is False

    def test_requires_human_on_no_consensus(self):
        f = self._make_filter([1, 3, 5])
        result = f.evaluate_sync(RUBY_SAMPLE, PYTHON_SAMPLE, "ruby->python")
        assert result.requires_human is True

    def test_ratings_returned(self):
        f = self._make_filter([4, 4, 5])
        result = f.evaluate_sync(RUBY_SAMPLE, PYTHON_SAMPLE, "ruby->python")
        assert len(result.ratings) == 3

    def test_rating_from_text_numeric(self):
        assert Rating.from_text("RATING: 4") == Rating.GOOD

    def test_rating_from_text_keyword(self):
        assert Rating.from_text("looks great and perfect") == Rating.GREAT

    def test_rating_from_text_fallback(self):
        assert Rating.from_text("hmm, maybe") == Rating.OK


# ── Dataset Tests (mocked Supabase) ──────────────────────────────────────────

class TestDatasetManager:
    def _make_manager(self) -> DatasetManager:
        mock_db = MagicMock()
        mock_db.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": 1, "status": "accepted"}
        ]
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value \
            .limit.return_value.execute.return_value.data = []
        return DatasetManager(supabase_client=mock_db)

    def test_insert_returns_row(self):
        dm = self._make_manager()
        pair = TrainingPair(
            pair_id="ruby->python",
            source_lang="ruby",
            target_lang="python",
            source_code=RUBY_SAMPLE,
            target_code=PYTHON_SAMPLE,
            quality_score=0.9,
            status="accepted",
        )
        result = dm.insert(pair)
        assert result["id"] == 1

    def test_insert_calls_supabase(self):
        mock_db = MagicMock()
        mock_db.table.return_value.insert.return_value.execute.return_value.data = [{"id": 2}]
        dm = DatasetManager(supabase_client=mock_db)
        pair = TrainingPair(
            pair_id="ruby->python",
            source_lang="ruby",
            target_lang="python",
            source_code="puts 'hi'",
            target_code="print('hi')",
            status="accepted",
        )
        dm.insert(pair)
        mock_db.table.assert_called_with("training_pairs")
        mock_db.table.return_value.insert.assert_called_once()


# ── Crawler Tests (mocked HTTP) ───────────────────────────────────────────────

class TestGitHubCrawler:
    def test_crawl_language_unknown_raises(self):
        crawler = GitHubCrawler()
        with pytest.raises(ValueError, match="Unsupported language"):
            list(crawler.crawl_language("cobol"))

    def test_crawl_seed_repos_empty_for_unknown(self):
        crawler = GitHubCrawler()
        snippets = list(crawler.crawl_seed_repos("unknown_lang"))
        assert snippets == []

    def test_config_defaults(self):
        cfg = CrawlerConfig()
        assert cfg.max_repos == 5
        assert cfg.max_files_per_repo == 10
        assert cfg.min_file_size == 200
