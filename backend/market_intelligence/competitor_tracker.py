"""Tracks competitor GitHub repositories for new releases and activity."""
from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Optional
import urllib.request
import urllib.error
import json

COMPETITORS = [
    {"name": "LangChain", "repo": "langchain-ai/langchain"},
    {"name": "CrewAI", "repo": "crewAIInc/crewAI"},
    {"name": "AutoGPT", "repo": "Significant-Gravitas/AutoGPT"},
    {"name": "LlamaIndex", "repo": "run-llama/llama_index"},
    {"name": "AutoGen", "repo": "microsoft/autogen"},
]

GITHUB_API = "https://api.github.com"


def _get(url: str, token: Optional[str] = None) -> dict | list:
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "TokenBroker-MarketIntel/1.0")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


class CompetitorTracker:
    def __init__(self, github_token: Optional[str] = None):
        self.token = github_token or os.getenv("GITHUB_TOKEN")

    def get_repo_stats(self, repo: str) -> dict:
        try:
            data = _get(f"{GITHUB_API}/repos/{repo}", self.token)
            return {
                "repo": repo,
                "stars": data.get("stargazers_count", 0),
                "forks": data.get("forks_count", 0),
                "open_issues": data.get("open_issues_count", 0),
                "last_push": data.get("pushed_at", ""),
                "description": data.get("description", ""),
            }
        except Exception as exc:
            return {"repo": repo, "error": str(exc)}

    def get_latest_release(self, repo: str) -> dict:
        try:
            data = _get(f"{GITHUB_API}/repos/{repo}/releases/latest", self.token)
            return {
                "repo": repo,
                "tag": data.get("tag_name", ""),
                "name": data.get("name", ""),
                "published_at": data.get("published_at", ""),
                "url": data.get("html_url", ""),
                "body_preview": (data.get("body") or "")[:300],
            }
        except Exception as exc:
            return {"repo": repo, "error": str(exc)}

    def scan_all(self) -> list[dict]:
        results = []
        for c in COMPETITORS:
            stats = self.get_repo_stats(c["repo"])
            release = self.get_latest_release(c["repo"])
            results.append({
                "name": c["name"],
                "stats": stats,
                "latest_release": release,
                "scanned_at": datetime.now(timezone.utc).isoformat(),
            })
        return results
