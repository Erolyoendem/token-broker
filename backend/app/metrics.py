"""In-memory request/error counters for /stats/errors endpoint."""
from __future__ import annotations
from collections import defaultdict

_request_counts: dict[str, int] = defaultdict(int)
_error_counts: dict[str, int] = defaultdict(int)


def record_request(path: str, status_code: int) -> None:
    _request_counts[path] += 1
    if status_code >= 400:
        _error_counts[path] += 1


def get_error_rates() -> list[dict]:
    result = []
    for path, total in _request_counts.items():
        errors = _error_counts.get(path, 0)
        result.append({
            "endpoint": path,
            "requests": total,
            "errors": errors,
            "error_rate": round(errors / total * 100, 1) if total > 0 else 0.0,
        })
    return sorted(result, key=lambda x: x["error_rate"], reverse=True)


def reset() -> None:
    """For tests."""
    _request_counts.clear()
    _error_counts.clear()
