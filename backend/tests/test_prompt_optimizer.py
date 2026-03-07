"""Tests for PromptOptimizer: Thompson Sampling, mutation, and full cycle."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agent_swarm.memory import SwarmMemory
from agent_swarm.prompt_optimizer import PromptOptimizer, _thompson_sample, MUTATIONS


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_memory(stats: dict[str, dict]) -> SwarmMemory:
    """Create a SwarmMemory backed by a temp file, pre-seeded with stats."""
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    state = {
        "conversions": [],
        "prompt_variants": stats,
        "run_summaries": [],
        "meta": {"total_conversions": 0, "total_tokens": 0,
                 "created_at": "", "last_updated": ""},
    }
    Path(tmp.name).write_text(json.dumps(state))
    return SwarmMemory(Path(tmp.name))


BASE_VARIANTS = {
    "v1_minimal": "You are a Ruby-to-Python code converter. Output only valid Python code.",
    "v2_structured": "You are an expert software engineer. Convert the given Ruby code to idiomatic Python 3.",
    "v3_examples": "Convert Ruby to Python. Follow these rules strictly:\n1. Output only Python code.",
}


# ── Thompson Sampling ──────────────────────────────────────────────────────────

def test_thompson_sample_returns_float_in_range():
    for _ in range(20):
        s = _thompson_sample(calls=10, successes=8)
        assert 0.0 <= s <= 1.0


def test_thompson_sample_high_success_skews_high():
    """High success rate → samples should on average exceed 0.5."""
    samples = [_thompson_sample(100, 95) for _ in range(200)]
    assert sum(samples) / len(samples) > 0.7


def test_thompson_sample_low_success_skews_low():
    samples = [_thompson_sample(100, 5) for _ in range(200)]
    assert sum(samples) / len(samples) < 0.3


def test_select_variant_prefers_high_success():
    """Over many trials, the variant with highest success rate wins most."""
    stats = {
        "v1_minimal":    {"calls": 100, "successes": 90, "success_rate": 0.9, "avg_tokens": 50},
        "v2_structured": {"calls": 100, "successes": 30, "success_rate": 0.3, "avg_tokens": 50},
        "v3_examples":   {"calls": 100, "successes": 50, "success_rate": 0.5, "avg_tokens": 50},
    }
    mem = _make_memory({
        "v1_minimal":    {"calls": 100, "successes": 90, "total_tokens": 5000},
        "v2_structured": {"calls": 100, "successes": 30, "total_tokens": 3000},
        "v3_examples":   {"calls": 100, "successes": 50, "total_tokens": 5000},
    })
    optimizer = PromptOptimizer(mem)
    counts: dict[str, int] = {"v1_minimal": 0, "v2_structured": 0, "v3_examples": 0}
    for _ in range(300):
        chosen = optimizer.select_variant(list(stats.keys()))
        counts[chosen] = counts.get(chosen, 0) + 1

    # v1_minimal (90% success) should win the majority of selections
    assert counts["v1_minimal"] > counts["v2_structured"]
    assert counts["v1_minimal"] > counts["v3_examples"]


def test_select_variant_explores_unseen_first():
    """Unseen variant must be returned immediately (priority exploration)."""
    mem = _make_memory({"v1_minimal": {"calls": 50, "successes": 40, "total_tokens": 2000}})
    optimizer = PromptOptimizer(mem)
    chosen = optimizer.select_variant(["v1_minimal", "v_unseen"])
    assert chosen == "v_unseen"


# ── Mutation ──────────────────────────────────────────────────────────────────

def test_mutate_prompt_changes_text():
    mem = _make_memory({})
    optimizer = PromptOptimizer(mem)
    _, mutated = optimizer.mutate_prompt("v1_minimal", BASE_VARIANTS["v1_minimal"])
    assert mutated != BASE_VARIANTS["v1_minimal"]


def test_mutate_prompt_returns_new_id():
    mem = _make_memory({})
    optimizer = PromptOptimizer(mem)
    new_id, _ = optimizer.mutate_prompt("v1_minimal", BASE_VARIANTS["v1_minimal"])
    assert new_id != "v1_minimal"
    assert "v1_minimal" in new_id  # derived from parent


def test_mutate_prompt_applies_suffix_when_no_match():
    """A prompt with no mutation keywords gets the exploration suffix."""
    mem = _make_memory({})
    optimizer = PromptOptimizer(mem)
    unique_text = "Translate code XYZ_UNIQUE_NO_MATCH to Python."
    new_id, mutated = optimizer.mutate_prompt("base", unique_text)
    assert mutated != unique_text
    assert "Output only the converted Python code" in mutated


# ── Full optimization cycle ────────────────────────────────────────────────────

def test_optimization_cycle_replaces_worst_variant():
    """Worst performer should be replaced; champion must survive."""
    mem = _make_memory({
        "v1_minimal":    {"calls": 50, "successes": 45, "total_tokens": 2500},  # best
        "v2_structured": {"calls": 50, "successes": 10, "total_tokens": 500},   # worst
        "v3_examples":   {"calls": 50, "successes": 25, "total_tokens": 1250},  # mid
    })
    optimizer = PromptOptimizer(mem, worst_cutoff=0.34)
    updated = optimizer.run_optimization_cycle(dict(BASE_VARIANTS))

    # Champion must survive
    assert "v1_minimal" in updated
    # At least one mutation was added
    mutations = [vid for vid in updated if "mut" in vid]
    assert len(mutations) >= 1
    # Total variant count unchanged (replace, not add)
    assert len(updated) == len(BASE_VARIANTS)


def test_optimization_cycle_never_removes_champion():
    """Champion (best variant) must never be removed."""
    mem = _make_memory({
        "v1_minimal":    {"calls": 200, "successes": 199, "total_tokens": 10000},
        "v2_structured": {"calls": 10,  "successes": 1,   "total_tokens": 200},
        "v3_examples":   {"calls": 10,  "successes": 2,   "total_tokens": 200},
    })
    optimizer = PromptOptimizer(mem, worst_cutoff=0.5)
    updated = optimizer.run_optimization_cycle(dict(BASE_VARIANTS))
    assert "v1_minimal" in updated


def test_optimization_cycle_empty_variants_no_crash():
    mem = _make_memory({})
    optimizer = PromptOptimizer(mem)
    result = optimizer.run_optimization_cycle({})
    assert result == {}
