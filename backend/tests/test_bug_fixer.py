"""Tests for infra/bug_fixer.py – all external calls are mocked."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Make infra/ importable from the tests directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "infra"))
import bug_fixer as bf


# ── parse_errors ──────────────────────────────────────────────────────────────

SAMPLE_LOG_500 = """\
2026-03-07T10:01:00 INFO  GET /health HTTP 200
2026-03-07T10:02:00 ERROR "POST /chat" HTTP 500 Internal Server Error
2026-03-07T10:02:01 ERROR Traceback (most recent call last):
2026-03-07T10:02:01 ERROR   File "app/main.py", line 270, in chat
2026-03-07T10:02:01 ERROR     result, provider = await call_with_fallback(...)
2026-03-07T10:02:01 ERROR RuntimeError: All providers failed
2026-03-07T10:03:00 INFO  GET /health HTTP 200
"""

SAMPLE_LOG_NO_ERRORS = """\
2026-03-07T10:01:00 INFO  GET /health HTTP 200
2026-03-07T10:01:30 INFO  POST /chat HTTP 200
2026-03-07T10:02:00 INFO  GET /providers HTTP 200
"""

SAMPLE_LOG_MULTI = """\
2026-03-07T10:01:00 ERROR "GET /usage/abc" HTTP 500 Internal Server Error
2026-03-07T10:01:00 ERROR RuntimeError: DB connection lost
2026-03-07T10:02:00 ERROR "POST /group-buys" HTTP 502 Bad Gateway
2026-03-07T10:02:00 ERROR httpx.ConnectError: upstream refused
2026-03-07T10:03:00 ERROR "GET /usage/abc" HTTP 500 Internal Server Error
"""


class TestParseErrors:
    def test_parses_500_error(self):
        errors = bf.parse_errors(SAMPLE_LOG_500)
        assert len(errors) == 1
        e = errors[0]
        assert e.status_code == 500
        assert e.url == "/chat"
        assert e.method == "POST"

    def test_no_errors_in_clean_log(self):
        errors = bf.parse_errors(SAMPLE_LOG_NO_ERRORS)
        assert errors == []

    def test_multiple_distinct_errors(self):
        errors = bf.parse_errors(SAMPLE_LOG_MULTI)
        codes = {e.status_code for e in errors}
        assert 500 in codes
        assert 502 in codes

    def test_deduplication_by_fingerprint(self):
        # Exact same log line repeated → same fingerprint → deduplicated to 1
        repeated = (
            '2026-03-07T10:01:00 ERROR "GET /usage/abc" HTTP 500 Internal Server Error\n'
            '2026-03-07T10:01:00 ERROR RuntimeError: DB connection lost\n'
            '2026-03-07T10:01:00 ERROR "GET /usage/abc" HTTP 500 Internal Server Error\n'
            '2026-03-07T10:01:00 ERROR RuntimeError: DB connection lost\n'
        )
        errors = bf.parse_errors(repeated)
        assert len(errors) == 1
        assert errors[0].url == "/usage/abc"

    def test_stacktrace_extracted(self):
        errors = bf.parse_errors(SAMPLE_LOG_500)
        assert "RuntimeError" in errors[0].stacktrace or "call_with_fallback" in errors[0].stacktrace

    def test_timestamp_extracted(self):
        errors = bf.parse_errors(SAMPLE_LOG_500)
        assert "2026-03-07" in errors[0].timestamp

    def test_fingerprint_is_stable(self):
        errors1 = bf.parse_errors(SAMPLE_LOG_500)
        errors2 = bf.parse_errors(SAMPLE_LOG_500)
        assert errors1[0].fingerprint == errors2[0].fingerprint

    def test_fingerprint_differs_for_different_errors(self):
        e1 = bf.ParsedError("HTTP 500", 500, "/chat", "POST", "RuntimeError", "log", timestamp="")
        e2 = bf.ParsedError("HTTP 502", 502, "/health", "GET", "ConnectError", "log", timestamp="")
        assert e1.fingerprint != e2.fingerprint

    def test_parse_error_alias(self):
        """parse_error() is an alias for parse_errors()."""
        result = bf.parse_error(SAMPLE_LOG_500)
        assert isinstance(result, list)


# ── fetch_recent_errors ───────────────────────────────────────────────────────

class TestFetchRecentErrors:
    def test_returns_string(self):
        with patch("bug_fixer.RAILWAY_TOKEN", ""), \
             patch("bug_fixer.RAILWAY_SERVICE_ID", ""), \
             patch("bug_fixer._fetch_via_health_probe", return_value="[INFO] OK\n"):
            result = bf.fetch_recent_errors(lines=10)
        assert isinstance(result, str)

    def test_cli_fallback_on_missing_token(self):
        with patch("bug_fixer.RAILWAY_TOKEN", ""), \
             patch("bug_fixer._fetch_via_health_probe", return_value="health-log\n") as mock_probe:
            result = bf.fetch_recent_errors()
        mock_probe.assert_called_once()
        assert result == "health-log\n"

    def test_cli_used_when_token_set(self):
        with patch("bug_fixer.RAILWAY_TOKEN", "rly_test"), \
             patch("bug_fixer._fetch_via_cli", return_value="cli-log\n") as mock_cli:
            result = bf.fetch_recent_errors()
        mock_cli.assert_called_once()
        assert result == "cli-log\n"

    def test_health_probe_ok_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("bug_fixer.RAILWAY_TOKEN", ""), \
             patch("bug_fixer.RAILWAY_SERVICE_ID", ""), \
             patch("httpx.get", return_value=mock_resp):
            result = bf._fetch_via_health_probe()
        assert "200" in result
        assert "ERROR" not in result

    def test_health_probe_5xx_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        with patch("bug_fixer.RAILWAY_TOKEN", ""), \
             patch("httpx.get", return_value=mock_resp):
            result = bf._fetch_via_health_probe()
        assert "ERROR" in result
        assert "503" in result or "unhealthy" in result.lower()

    def test_health_probe_connection_error(self):
        with patch("httpx.get", side_effect=Exception("connection refused")):
            result = bf._fetch_via_health_probe()
        assert "ERROR" in result
        assert "connection refused" in result


# ── generate_fix ──────────────────────────────────────────────────────────────

class TestGenerateFix:
    def _make_error(self) -> bf.ParsedError:
        return bf.ParsedError(
            error_type="HTTP 500",
            status_code=500,
            url="/chat",
            method="POST",
            stacktrace="RuntimeError: All providers failed",
            raw_log="POST /chat HTTP 500\nRuntimeError: All providers failed",
            timestamp="2026-03-07T10:02:00",
        )

    def test_returns_none_without_api_key(self):
        with patch("bug_fixer.TOKENBROKER_API_KEY", ""):
            result = bf.generate_fix(self._make_error())
        assert result is None

    def test_returns_fix_on_valid_response(self):
        llm_response = json.dumps({
            "explanation": "The provider pool is empty.",
            "patch": "--- a/app/router.py\n+++ b/app/router.py\n@@ -1 +1 @@\n+fallback = True",
            "files_changed": ["backend/app/router.py"],
            "confidence": "high",
        })
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": llm_response}}]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("bug_fixer.TOKENBROKER_API_KEY", "tkb_test"), \
             patch("httpx.post", return_value=mock_resp):
            fix = bf.generate_fix(self._make_error())

        assert fix is not None
        assert fix.explanation == "The provider pool is empty."
        assert "router.py" in fix.patch
        assert fix.files_changed == ["backend/app/router.py"]

    def test_skips_low_confidence(self):
        llm_response = json.dumps({
            "explanation": "Not sure.",
            "patch": "",
            "files_changed": [],
            "confidence": "low",
        })
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": llm_response}}]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("bug_fixer.TOKENBROKER_API_KEY", "tkb_test"), \
             patch("httpx.post", return_value=mock_resp):
            fix = bf.generate_fix(self._make_error())

        assert fix is None

    def test_handles_markdown_wrapped_json(self):
        llm_response = '```json\n{"explanation":"Root cause","patch":"diff","files_changed":[],"confidence":"medium"}\n```'
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": llm_response}}]}
        mock_resp.raise_for_status = MagicMock()

        with patch("bug_fixer.TOKENBROKER_API_KEY", "tkb_test"), \
             patch("httpx.post", return_value=mock_resp):
            fix = bf.generate_fix(self._make_error())

        assert fix is not None
        assert fix.explanation == "Root cause"

    def test_returns_none_on_http_error(self):
        with patch("bug_fixer.TOKENBROKER_API_KEY", "tkb_test"), \
             patch("httpx.post", side_effect=Exception("timeout")):
            fix = bf.generate_fix(self._make_error())
        assert fix is None


# ── apply_fix (dry-run only) ──────────────────────────────────────────────────

class TestApplyFix:
    def _make_fix(self) -> bf.GeneratedFix:
        error = bf.ParsedError("HTTP 500", 500, "/chat", "POST",
                               "RuntimeError", "log chunk", timestamp="2026-03-07T10:00:00")
        return bf.GeneratedFix(
            error=error,
            explanation="Provider pool exhausted.",
            patch="--- a/router.py\n+++ b/router.py\n@@ -10 +10 @@\n+fallback = True",
            files_changed=["backend/app/router.py"],
        )

    def test_dry_run_returns_none(self):
        fix = self._make_fix()
        result = bf.apply_fix(fix, dry_run=True)
        assert result is None

    def test_dry_run_sets_branch_name(self):
        fix = self._make_fix()
        bf.apply_fix(fix, dry_run=True)
        assert fix.branch.startswith("fix/5xx-")

    def test_render_proposal_contains_key_fields(self):
        fix = self._make_fix()
        fix.branch = "fix/5xx-abc123-1234567"
        proposal = bf._render_proposal(fix)
        assert "500" in proposal
        assert "/chat" in proposal
        assert "Provider pool exhausted" in proposal
        assert "router.py" in proposal

    def test_render_pr_body_contains_checklist(self):
        fix = self._make_fix()
        fix.branch = "fix/5xx-abc123-1234567"
        body = bf._render_pr_body(fix)
        assert "Review Checklist" in body
        assert "human review required" in body.lower()
        assert "500" in body
