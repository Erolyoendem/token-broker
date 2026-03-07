"""Tests for market_intelligence package."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from market_intelligence.competitor_tracker import CompetitorTracker
from market_intelligence.trend_analyzer import TrendAnalyzer
from market_intelligence.opportunity_detector import OpportunityDetector, OWN_FEATURES
from market_intelligence.report_generator import ReportGenerator


# ── CompetitorTracker ─────────────────────────────────────────────────────────

MOCK_REPO = {
    "stargazers_count": 42000,
    "forks_count": 5000,
    "open_issues_count": 123,
    "pushed_at": "2026-03-01T12:00:00Z",
    "description": "A test repo",
}

MOCK_RELEASE = {
    "tag_name": "v0.9.0",
    "name": "Release 0.9.0",
    "published_at": "2026-03-01T10:00:00Z",
    "html_url": "https://github.com/test/test/releases/tag/v0.9.0",
    "body": "Bug fixes and performance improvements.",
}


def _mock_get(url, token=None):
    if "/releases/latest" in url:
        return MOCK_RELEASE
    return MOCK_REPO


def test_competitor_tracker_get_repo_stats():
    tracker = CompetitorTracker(github_token="fake")
    with patch("market_intelligence.competitor_tracker._get", side_effect=_mock_get):
        stats = tracker.get_repo_stats("test/repo")
    assert stats["stars"] == 42000
    assert stats["forks"] == 5000
    assert stats["repo"] == "test/repo"


def test_competitor_tracker_get_latest_release():
    tracker = CompetitorTracker(github_token="fake")
    with patch("market_intelligence.competitor_tracker._get", side_effect=_mock_get):
        release = tracker.get_latest_release("test/repo")
    assert release["tag"] == "v0.9.0"
    assert release["url"] == MOCK_RELEASE["html_url"]


def test_competitor_tracker_scan_all():
    tracker = CompetitorTracker(github_token="fake")
    with patch("market_intelligence.competitor_tracker._get", side_effect=_mock_get):
        results = tracker.scan_all()
    assert len(results) == 5  # 5 configured competitors
    for entry in results:
        assert "name" in entry
        assert "stats" in entry
        assert "latest_release" in entry


def test_competitor_tracker_handles_http_error():
    import urllib.error
    tracker = CompetitorTracker()
    with patch("market_intelligence.competitor_tracker._get",
               side_effect=urllib.error.URLError("connection refused")):
        stats = tracker.get_repo_stats("test/fail")
    assert "error" in stats


# ── TrendAnalyzer ─────────────────────────────────────────────────────────────

MOCK_ARXIV_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>https://arxiv.org/abs/2501.00001</id>
    <title>Multi-Agent LLM Orchestration Survey</title>
    <summary>A comprehensive survey of multi-agent systems.</summary>
    <published>2026-01-01T00:00:00Z</published>
  </entry>
</feed>"""


def test_trend_analyzer_returns_structure():
    import urllib.request
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = MOCK_ARXIV_XML

    with patch("urllib.request.urlopen", return_value=mock_resp):
        analyzer = TrendAnalyzer()
        result = analyzer.analyze(max_per_term=1)

    assert "analyzed_at" in result
    assert "papers" in result
    assert result["total_papers"] > 0


def test_trend_analyzer_top_keywords():
    analyzer = TrendAnalyzer()
    mock_analysis = {
        "papers": {
            "multi-agent LLM": [
                {"title": "Multi-Agent Orchestration Systems", "url": "https://arxiv.org/abs/1"},
                {"title": "Agentic Token Optimization Framework", "url": "https://arxiv.org/abs/2"},
            ]
        }
    }
    keywords = analyzer.top_keywords(mock_analysis)
    assert isinstance(keywords, list)
    assert len(keywords) <= 15


# ── OpportunityDetector ───────────────────────────────────────────────────────

def test_opportunity_detector_returns_gaps():
    detector = OpportunityDetector()
    result = detector.detect()
    assert "gaps" in result
    assert "unique_advantages" in result
    assert "top_recommendations" in result
    assert isinstance(result["gaps"], list)


def test_opportunity_detector_unique_advantages_subset_of_own_features():
    detector = OpportunityDetector()
    result = detector.detect()
    for adv in result["unique_advantages"]:
        assert adv in OWN_FEATURES


def test_opportunity_detector_recommendations_have_required_fields():
    detector = OpportunityDetector()
    result = detector.detect()
    for rec in result["top_recommendations"]:
        assert "feature" in rec
        assert "priority" in rec
        assert "adopted_by" in rec
        assert "suggestion" in rec


def test_opportunity_detector_with_competitor_scan():
    detector = OpportunityDetector()
    scan = [
        {
            "name": "TestComp",
            "latest_release": {
                "tag": "v1.0",
                "published_at": "2026-01-01",
                "url": "https://example.com",
                "body_preview": "Major release",
            }
        }
    ]
    result = detector.detect(competitor_scan=scan)
    assert len(result["recent_competitor_releases"]) == 1
    assert result["recent_competitor_releases"][0]["competitor"] == "TestComp"


# ── ReportGenerator ───────────────────────────────────────────────────────────

def test_report_generator_creates_markdown_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        reporter = ReportGenerator(
            reports_dir=Path(tmpdir) / "reports",
            strategy_dir=Path(tmpdir) / "strategy",
        )
        competitors = [{"name": "TestComp", "stats": {"stars": 1000, "forks": 100,
                        "open_issues": 5, "last_push": "2026-01-01"},
                        "latest_release": {"tag": "v1.0", "url": "https://example.com",
                                           "published_at": "2026-01-01", "body_preview": ""}}]
        trends = {"analyzed_at": "2026-01-01", "terms": ["test"], "papers": {"test": []}, "total_papers": 0}
        opp = {"unique_advantages": ["group_buying"], "top_recommendations": [], "recent_competitor_releases": []}

        path = reporter.generate_weekly_report(competitors, trends, opp)
        assert path.exists()
        content = path.read_text()
        assert "TokenBroker" in content
        assert "TestComp" in content


def test_report_generator_creates_strategy_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        reporter = ReportGenerator(
            reports_dir=Path(tmpdir) / "reports",
            strategy_dir=Path(tmpdir) / "strategy",
        )
        opp = {
            "top_recommendations": [
                {"feature": "streaming", "priority": 9,
                 "adopted_by": ["LangChain"], "suggestion": "Implement streaming"}
            ]
        }
        path = reporter.generate_strategy_suggestions(opp)
        assert path.exists()
        content = path.read_text()
        assert "Strategy" in content
        assert "streaming" in content.lower()


# ── API endpoint ──────────────────────────────────────────────────────────────

def test_market_analysis_endpoint_requires_admin_key():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    resp = client.get("/market/analysis")
    assert resp.status_code == 422  # missing header

    resp2 = client.get("/market/analysis", headers={"X-Admin-Key": "wrong"})
    assert resp2.status_code == 403


def test_market_opportunities_endpoint():
    from fastapi.testclient import TestClient
    from app.main import app
    import app.main as main_module
    client = TestClient(app)
    with patch.object(main_module, "ADMIN_API_KEY", "test_admin_key"):
        resp = client.get("/market/opportunities", headers={"X-Admin-Key": "test_admin_key"})
    assert resp.status_code == 200
    data = resp.json()
    assert "gaps" in data
    assert "top_recommendations" in data
