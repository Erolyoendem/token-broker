"""Analyzes arXiv publications for multi-agent AI trends."""
from __future__ import annotations
import urllib.request
import urllib.parse
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ARXIV_API = "https://export.arxiv.org/api/query"
SEARCH_TERMS = [
    "multi-agent LLM",
    "agentic AI orchestration",
    "LLM token optimization",
    "AI marketplace tokens",
]

NS = {"atom": "http://www.w3.org/2005/Atom"}


def _search_arxiv(query: str, max_results: int = 5) -> list[dict]:
    params = urllib.parse.urlencode({
        "search_query": f"all:{urllib.parse.quote(query)}",
        "max_results": max_results,
        "sortBy": "lastUpdatedDate",
        "sortOrder": "descending",
    })
    url = f"{ARXIV_API}?{params}"
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "TokenBroker-MarketIntel/1.0")
        with urllib.request.urlopen(req, timeout=15) as resp:
            root = ET.fromstring(resp.read())
    except Exception as exc:
        return [{"error": str(exc), "query": query}]

    papers = []
    for entry in root.findall("atom:entry", NS):
        title_el = entry.find("atom:title", NS)
        summary_el = entry.find("atom:summary", NS)
        published_el = entry.find("atom:published", NS)
        id_el = entry.find("atom:id", NS)
        papers.append({
            "title": (title_el.text or "").strip() if title_el is not None else "",
            "summary": (summary_el.text or "").strip()[:300] if summary_el is not None else "",
            "published": (published_el.text or "").strip() if published_el is not None else "",
            "url": (id_el.text or "").strip() if id_el is not None else "",
            "query": query,
        })
    return papers


class TrendAnalyzer:
    def analyze(self, max_per_term: int = 3) -> dict:
        results = {}
        for term in SEARCH_TERMS:
            results[term] = _search_arxiv(term, max_per_term)
        return {
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "terms": SEARCH_TERMS,
            "papers": results,
            "total_papers": sum(len(v) for v in results.values()),
        }

    def top_keywords(self, analysis: dict) -> list[str]:
        """Extract frequently appearing keywords from paper titles."""
        from collections import Counter
        words: list[str] = []
        for papers in analysis.get("papers", {}).values():
            for p in papers:
                if "error" not in p:
                    words.extend(
                        w.lower().strip(".,()[]")
                        for w in p.get("title", "").split()
                        if len(w) > 4
                    )
        common = Counter(words).most_common(15)
        return [w for w, _ in common]
