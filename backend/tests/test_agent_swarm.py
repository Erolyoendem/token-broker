"""
Tests for the agent_swarm package.

Covers:
  - SwarmMemory: persistence, prompt stats, epsilon-greedy selection
  - EvaluationAgent: scoring logic (syntax, structure, idioms)
  - GenerationAgent: prompt selection, fallback on HTTP error
  - Orchestrator: end-to-end pipeline with mocked HTTP, fallback on crash
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── make agent_swarm importable from tests/ ──────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_swarm.memory import SwarmMemory
from agent_swarm.evaluation_agent import EvaluationAgent, evaluate_code
from agent_swarm.generation_agent import GenerationAgent
from agent_swarm.orchestrator import Orchestrator

# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_RUBY = """\
class Greeter
  def initialize(name)
    @name = name
  end
  def greet
    puts "Hello, #{@name}!"
  end
end
"""

GOOD_PYTHON = """\
class Greeter:
    def __init__(self, name):
        self.name = name
    def greet(self):
        print(f"Hello, {self.name}!")
"""

BAD_PYTHON = "class Greeter  # missing colon\n    pass"

RUBY_ISM_PYTHON = "puts = 1\nend_result = puts + 1\nattr_accessor = 'x'\n"


@pytest.fixture
def tmp_memory(tmp_path):
    return SwarmMemory(path=tmp_path / "test_memory.json")


# ── SwarmMemory tests ─────────────────────────────────────────────────────────

def test_memory_starts_empty(tmp_memory):
    stats = tmp_memory.aggregate_stats()
    assert stats["total_conversions"] == 0
    assert stats["success_rate"] == 0.0


def test_memory_add_conversion(tmp_memory):
    tmp_memory.add_conversion(
        filename="hello.rb",
        ruby_code=SAMPLE_RUBY,
        python_code=GOOD_PYTHON,
        score=0.9,
        tokens=120,
        elapsed_s=1.5,
        prompt_variant="v1_minimal",
    )
    stats = tmp_memory.aggregate_stats()
    assert stats["total_conversions"] == 1
    assert stats["avg_score"] == pytest.approx(0.9)


def test_memory_persists_to_disk(tmp_path):
    path = tmp_path / "mem.json"
    m1 = SwarmMemory(path=path)
    m1.add_conversion(
        filename="f.rb", ruby_code="x", python_code="y",
        score=0.8, tokens=50, elapsed_s=1.0, prompt_variant="v1_minimal",
    )
    # Re-load from same file
    m2 = SwarmMemory(path=path)
    assert m2.aggregate_stats()["total_conversions"] == 1


def test_prompt_stats_accumulate(tmp_memory):
    tmp_memory.record_prompt_result("v1_minimal", success=True,  tokens=100)
    tmp_memory.record_prompt_result("v1_minimal", success=False, tokens=80)
    tmp_memory.record_prompt_result("v2_structured", success=True, tokens=110)

    ps = tmp_memory.prompt_stats()
    assert ps["v1_minimal"]["calls"] == 2
    assert ps["v1_minimal"]["success_rate"] == pytest.approx(0.5)
    assert ps["v2_structured"]["success_rate"] == pytest.approx(1.0)


def test_best_prompt_always_tries_unseen(tmp_memory):
    """An unseen variant is returned immediately (no calls yet)."""
    available = ["v1_minimal", "v2_structured", "v3_examples"]
    tmp_memory.record_prompt_result("v1_minimal", success=True, tokens=100)
    # v2_structured and v3_examples unseen → one of them should be returned
    best = tmp_memory.best_prompt_variant(available, epsilon=0.0)
    assert best in ("v2_structured", "v3_examples")


def test_best_prompt_exploits_highest_rate(tmp_memory):
    tmp_memory.record_prompt_result("v1_minimal",    success=False, tokens=100)
    tmp_memory.record_prompt_result("v1_minimal",    success=False, tokens=100)
    tmp_memory.record_prompt_result("v2_structured", success=True,  tokens=100)
    tmp_memory.record_prompt_result("v2_structured", success=True,  tokens=100)
    tmp_memory.record_prompt_result("v3_examples",   success=False, tokens=100)
    # epsilon=0 → always exploit; only v2_structured has 100% rate
    best = tmp_memory.best_prompt_variant(
        ["v1_minimal", "v2_structured", "v3_examples"], epsilon=0.0
    )
    assert best == "v2_structured"


# ── EvaluationAgent tests ─────────────────────────────────────────────────────

def test_evaluation_good_python():
    result = evaluate_code(SAMPLE_RUBY, GOOD_PYTHON)
    assert result["score"] >= 0.75
    assert result["scores"]["syntax"] == 1.0


def test_evaluation_syntax_error():
    result = evaluate_code(SAMPLE_RUBY, BAD_PYTHON)
    assert result["score"] == 0.0
    assert "SyntaxError" in result["feedback"]


def test_evaluation_ruby_isms_penalised():
    result = evaluate_code("puts 'hi'", RUBY_ISM_PYTHON)
    assert result["scores"]["idioms"] < 1.0


def test_evaluation_agent_async():
    agent = EvaluationAgent("eval-test")
    task = {"filename": "hello.rb", "ruby_code": SAMPLE_RUBY, "python_code": GOOD_PYTHON}
    result = asyncio.get_event_loop().run_until_complete(agent.run(task))
    assert result["ok"] is True
    assert result["score"] >= 0.75


def test_evaluation_agent_empty_output():
    agent = EvaluationAgent("eval-test")
    task = {"filename": "hello.rb", "ruby_code": SAMPLE_RUBY, "python_code": ""}
    result = asyncio.get_event_loop().run_until_complete(agent.run(task))
    assert result["ok"] is False
    assert result["score"] == 0.0


# ── GenerationAgent tests ─────────────────────────────────────────────────────

def _make_mock_response(python_code: str, tokens: int = 150):
    """Build a fake aiohttp response for the proxy."""
    mock_resp = AsyncMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = AsyncMock(return_value={
        "choices": [{"message": {"content": python_code}}],
        "usage": {"total_tokens": tokens},
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


@pytest.mark.asyncio
async def test_generation_agent_success(tmp_memory):
    agent = GenerationAgent("gen-test", tmp_memory, epsilon=0.0)
    await agent.setup()

    mock_resp = _make_mock_response(GOOD_PYTHON, tokens=200)
    with patch.object(agent._session, "post", return_value=mock_resp):
        result = await agent.run({"filename": "hello.rb", "ruby_code": SAMPLE_RUBY})

    assert result["ok"] is True
    assert "class Greeter" in result["python_code"]
    assert result["tokens"] == 200
    await agent.teardown()


@pytest.mark.asyncio
async def test_generation_agent_http_error_returns_ok_false(tmp_memory):
    agent = GenerationAgent("gen-test", tmp_memory, epsilon=0.0)
    await agent.setup()

    mock_resp = AsyncMock()
    mock_resp.raise_for_status = MagicMock(side_effect=Exception("503 Service Unavailable"))
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    with patch.object(agent._session, "post", return_value=mock_resp):
        result = await agent.run({"filename": "hello.rb", "ruby_code": SAMPLE_RUBY})

    assert result["ok"] is False
    assert "503" in result["error"]
    await agent.teardown()


@pytest.mark.asyncio
async def test_generation_agent_records_in_memory(tmp_memory):
    agent = GenerationAgent("gen-test", tmp_memory, epsilon=0.0)
    await agent.setup()

    mock_resp = _make_mock_response(GOOD_PYTHON, tokens=120)
    with patch.object(agent._session, "post", return_value=mock_resp):
        await agent.run({"filename": "hello.rb", "ruby_code": SAMPLE_RUBY})

    stats = tmp_memory.prompt_stats()
    assert any(v["calls"] >= 1 for v in stats.values())
    await agent.teardown()


# ── Orchestrator tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_orchestrator_train_with_files(tmp_memory, tmp_path):
    # Create a small Ruby file in tmp dir
    (tmp_path / "hello.rb").write_text(SAMPLE_RUBY, encoding="utf-8")

    orchestrator = Orchestrator(tmp_memory, workers=1)

    # Patch GenerationAgent to return a fixed response without HTTP
    async def fake_run(self, task):
        return {
            "ok": True, "python_code": GOOD_PYTHON,
            "tokens": 100, "elapsed_s": 0.5,
            "prompt_variant": "v1_minimal", "error": "",
        }

    with patch("agent_swarm.orchestrator.GenerationAgent.run", fake_run):
        summary = await orchestrator.train(tmp_path)

    assert summary["files"] == 1
    assert summary["ok"] == 1
    assert summary["errors"] == 0
    assert summary["avg_score"] >= 0.5


@pytest.mark.asyncio
async def test_orchestrator_empty_dir(tmp_memory, tmp_path):
    orchestrator = Orchestrator(tmp_memory, workers=1)
    result = await orchestrator.train(tmp_path)
    assert "error" in result


@pytest.mark.asyncio
async def test_orchestrator_fallback_on_crash(tmp_memory, tmp_path):
    """Worker crash on one file must not stop processing of others."""
    (tmp_path / "a.rb").write_text(SAMPLE_RUBY, encoding="utf-8")
    (tmp_path / "b.rb").write_text(SAMPLE_RUBY, encoding="utf-8")

    orchestrator = Orchestrator(tmp_memory, workers=2)

    call_count = {"n": 0}

    async def flaky_run(self, task):
        call_count["n"] += 1
        if task["filename"] == "a.rb":
            raise RuntimeError("simulated crash")
        return {
            "ok": True, "python_code": GOOD_PYTHON,
            "tokens": 80, "elapsed_s": 0.3,
            "prompt_variant": "v1_minimal", "error": "",
        }

    with patch("agent_swarm.orchestrator.GenerationAgent.run", flaky_run):
        summary = await orchestrator.train(tmp_path)

    # b.rb should still succeed
    assert summary["files"] == 2
    assert summary["ok"] >= 1


@pytest.mark.asyncio
async def test_orchestrator_improves_across_runs(tmp_memory, tmp_path):
    """
    Demonstrates that the best_prompt_variant() converges over runs.
    After seeding memory with v2_structured success, it should be selected.
    """
    (tmp_path / "x.rb").write_text(SAMPLE_RUBY, encoding="utf-8")

    # Seed: v2_structured has been very successful
    for _ in range(5):
        tmp_memory.record_prompt_result("v2_structured", success=True, tokens=100)
    for _ in range(5):
        tmp_memory.record_prompt_result("v1_minimal", success=False, tokens=100)
    tmp_memory.record_prompt_result("v3_examples", success=False, tokens=100)

    selected_variants: list[str] = []

    async def tracking_run(self, task):
        selected_variants.append(self.memory.best_prompt_variant(
            ["v1_minimal", "v2_structured", "v3_examples"], epsilon=0.0
        ))
        return {
            "ok": True, "python_code": GOOD_PYTHON,
            "tokens": 100, "elapsed_s": 0.5,
            "prompt_variant": "v2_structured", "error": "",
        }

    orchestrator = Orchestrator(tmp_memory, workers=1)
    with patch("agent_swarm.orchestrator.GenerationAgent.run", tracking_run):
        await orchestrator.train(tmp_path)

    # With epsilon=0 exploitation, v2_structured should have been chosen
    assert "v2_structured" in selected_variants


def test_detect_gaps_identifies_repeated_failures(tmp_memory):
    for _ in range(3):
        tmp_memory.add_conversion(
            filename="hard.rb", ruby_code="complex", python_code="",
            score=0.0, tokens=0, elapsed_s=1.0, prompt_variant="v1_minimal",
        )
    tmp_memory.add_conversion(
        filename="easy.rb", ruby_code="simple", python_code=GOOD_PYTHON,
        score=0.9, tokens=100, elapsed_s=0.5, prompt_variant="v1_minimal",
    )
    orchestrator = Orchestrator(tmp_memory)
    gaps = orchestrator.detect_gaps()
    assert "hard.rb" in gaps
    assert "easy.rb" not in gaps
