"""
Benchmark task definitions.

Each BenchmarkTask specifies an input prompt, a category, and a validator
function that checks whether a model's response is correct.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class BenchmarkTask:
    id: str
    category: str           # math | code_gen | code_convert | factual | creative
    prompt: str
    validate: Callable[[str], tuple[bool, str]]   # (passed, note)
    difficulty: str = "medium"   # easy | medium | hard
    max_tokens: int = 512


# ── Validators ────────────────────────────────────────────────────────────────

def _expect_number(expected: str) -> Callable[[str], tuple[bool, str]]:
    """Response must contain a specific number."""
    def _validate(response: str) -> tuple[bool, str]:
        found = re.findall(r"-?\d+(?:\.\d+)?", response)
        ok = any(float(n) == float(expected) for n in found)
        return ok, f"expected {expected}, found {found[:3]}"
    return _validate


def _expect_keywords(*keywords: str) -> Callable[[str], tuple[bool, str]]:
    """Response must contain all listed keywords (case-insensitive)."""
    def _validate(response: str) -> tuple[bool, str]:
        lower = response.lower()
        missing = [k for k in keywords if k.lower() not in lower]
        return not missing, f"missing: {missing}" if missing else "ok"
    return _validate


def _valid_python_syntax(response: str) -> tuple[bool, str]:
    """Validate that the response contains syntactically correct Python."""
    # Extract code block if present
    m = re.search(r"```(?:python)?\n?(.*?)```", response, re.DOTALL)
    code = m.group(1) if m else response
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        fname = f.name
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", fname],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return True, "syntax ok"
    msg = (result.stderr or "").strip().splitlines()[0] if result.stderr else "syntax error"
    return False, msg


def _non_empty_creative(min_words: int = 30) -> Callable[[str], tuple[bool, str]]:
    def _validate(response: str) -> tuple[bool, str]:
        words = len(response.split())
        ok = words >= min_words
        return ok, f"{words} words (min {min_words})"
    return _validate


# ── Task Catalogue ────────────────────────────────────────────────────────────

TASKS: list[BenchmarkTask] = [

    # Math
    BenchmarkTask(
        id="math_001",
        category="math",
        difficulty="easy",
        prompt="What is 17 × 23? Reply with only the number.",
        validate=_expect_number("391"),
    ),
    BenchmarkTask(
        id="math_002",
        category="math",
        difficulty="medium",
        prompt=(
            "A train travels 120 km in 1.5 hours. "
            "What is its average speed in km/h? Answer with only the number."
        ),
        validate=_expect_number("80"),
    ),
    BenchmarkTask(
        id="math_003",
        category="math",
        difficulty="hard",
        prompt=(
            "What is the sum of all integers from 1 to 100? "
            "Show your reasoning, then state the final answer."
        ),
        validate=_expect_number("5050"),
    ),

    # Code generation
    BenchmarkTask(
        id="code_001",
        category="code_gen",
        difficulty="easy",
        prompt=(
            "Write a Python function `fibonacci(n)` that returns the n-th Fibonacci number "
            "(0-indexed, fib(0)=0, fib(1)=1). Include only the function definition."
        ),
        validate=_valid_python_syntax,
    ),
    BenchmarkTask(
        id="code_002",
        category="code_gen",
        difficulty="medium",
        prompt=(
            "Write a Python function `merge_sorted(a, b)` that merges two sorted lists "
            "into one sorted list without using built-in sort. Return only the code."
        ),
        validate=_valid_python_syntax,
    ),
    BenchmarkTask(
        id="code_003",
        category="code_gen",
        difficulty="hard",
        prompt=(
            "Write a Python class `LRUCache(capacity)` with `get(key)` and `put(key, value)` "
            "methods, O(1) time complexity. Return only the code."
        ),
        validate=_valid_python_syntax,
    ),

    # Code conversion
    BenchmarkTask(
        id="convert_001",
        category="code_convert",
        difficulty="easy",
        prompt=(
            "Convert this Ruby code to Python. Output only valid Python:\n\n"
            "class Greeter\n"
            "  def initialize(name)\n"
            "    @name = name\n"
            "  end\n"
            "  def greet\n"
            "    puts \"Hello, #{@name}!\"\n"
            "  end\n"
            "end"
        ),
        validate=_valid_python_syntax,
    ),
    BenchmarkTask(
        id="convert_002",
        category="code_convert",
        difficulty="medium",
        prompt=(
            "Convert this Ruby to Python. Output only valid Python:\n\n"
            "numbers = [1, 2, 3, 4, 5]\n"
            "evens = numbers.select { |n| n.even? }\n"
            "doubled = evens.map { |n| n * 2 }\n"
            "puts doubled.sum"
        ),
        validate=_valid_python_syntax,
    ),

    # Factual
    BenchmarkTask(
        id="factual_001",
        category="factual",
        difficulty="easy",
        prompt="What is the capital of France? Answer in one word.",
        validate=_expect_keywords("paris"),
    ),
    BenchmarkTask(
        id="factual_002",
        category="factual",
        difficulty="medium",
        prompt=(
            "Explain in 2-3 sentences what the Transformer architecture is "
            "and why it matters for large language models."
        ),
        validate=_expect_keywords("attention", "transformer"),
    ),
    BenchmarkTask(
        id="factual_003",
        category="factual",
        difficulty="medium",
        prompt="What does REST stand for and what are its key constraints? Be concise.",
        validate=_expect_keywords("representational", "state", "transfer"),
    ),

    # Creative
    BenchmarkTask(
        id="creative_001",
        category="creative",
        difficulty="easy",
        prompt=(
            "Write a short 4-line poem about open-source software. "
            "Be creative and original."
        ),
        validate=_non_empty_creative(min_words=10),
    ),
    BenchmarkTask(
        id="creative_002",
        category="creative",
        difficulty="medium",
        prompt=(
            "Write a 3-sentence product description for a fictional AI-powered "
            "token optimization service called TokenBroker."
        ),
        validate=_non_empty_creative(min_words=30),
    ),
]

TASK_MAP: dict[str, BenchmarkTask] = {t.id: t for t in TASKS}
CATEGORIES: list[str] = sorted({t.category for t in TASKS})


def get_task(task_id: str) -> BenchmarkTask:
    if task_id not in TASK_MAP:
        raise ValueError(f"Unknown task: {task_id}. Available: {list(TASK_MAP)}")
    return TASK_MAP[task_id]


def tasks_by_category(category: str) -> list[BenchmarkTask]:
    return [t for t in TASKS if t.category == category]
