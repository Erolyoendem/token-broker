"""
GitHub API crawler – collects open-source code snippets for training.

Uses the GitHub Search API to find repositories and extracts source files
for configured language pairs. Respects rate limits with exponential backoff.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Iterator

import httpx

log = logging.getLogger(__name__)

# GitHub language name → file extension
LANG_EXTENSIONS: dict[str, str] = {
    "ruby":       ".rb",
    "python":     ".py",
    "javascript": ".js",
    "typescript": ".ts",
    "java":       ".java",
}

# Repos known to contain clean, idiomatic code
SEED_REPOS: dict[str, list[str]] = {
    "ruby":       ["rubocop/rubocop", "rails/rails", "sinatra/sinatra"],
    "python":     ["psf/requests", "pallets/flask", "tiangolo/fastapi"],
    "javascript": ["expressjs/express", "lodash/lodash"],
}


@dataclass
class CodeSnippet:
    repo: str
    path: str
    language: str
    content: str
    size_bytes: int
    url: str


@dataclass
class CrawlerConfig:
    github_token: str = ""
    max_repos: int = 5
    max_files_per_repo: int = 10
    min_file_size: int = 200    # bytes – skip tiny files
    max_file_size: int = 8000   # bytes – skip huge files
    request_delay: float = 1.0  # seconds between requests


class GitHubCrawler:
    BASE = "https://api.github.com"

    def __init__(self, config: CrawlerConfig | None = None):
        self.cfg = config or CrawlerConfig()
        headers = {"Accept": "application/vnd.github+json"}
        if self.cfg.github_token:
            headers["Authorization"] = f"Bearer {self.cfg.github_token}"
        self._client = httpx.Client(
            headers=headers, timeout=30, follow_redirects=True
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def crawl_language(self, language: str) -> Iterator[CodeSnippet]:
        """Yield code snippets for the given language."""
        ext = LANG_EXTENSIONS.get(language)
        if not ext:
            raise ValueError(f"Unsupported language: {language}")

        repos = self._find_repos(language)
        log.info("Found %d repos for %s", len(repos), language)

        for repo in repos[: self.cfg.max_repos]:
            yield from self._crawl_repo(repo, language, ext)
            time.sleep(self.cfg.request_delay)

    def crawl_seed_repos(self, language: str) -> Iterator[CodeSnippet]:
        """Crawl known-good seed repositories for a language."""
        ext = LANG_EXTENSIONS.get(language, "")
        for repo in SEED_REPOS.get(language, []):
            yield from self._crawl_repo(repo, language, ext)
            time.sleep(self.cfg.request_delay)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _find_repos(self, language: str) -> list[str]:
        """Search GitHub for popular repositories in the given language."""
        params = {
            "q":        f"language:{language} stars:>500",
            "sort":     "stars",
            "order":    "desc",
            "per_page": self.cfg.max_repos,
        }
        try:
            resp = self._get(f"{self.BASE}/search/repositories", params=params)
            return [item["full_name"] for item in resp.get("items", [])]
        except Exception as e:
            log.warning("Repo search failed: %s – falling back to seeds", e)
            return SEED_REPOS.get(language, [])

    def _crawl_repo(
        self, repo: str, language: str, ext: str
    ) -> Iterator[CodeSnippet]:
        """Fetch source files from a repository."""
        log.info("Crawling %s", repo)
        try:
            tree = self._get(f"{self.BASE}/repos/{repo}/git/trees/HEAD", params={"recursive": "1"})
        except Exception as e:
            log.warning("Could not fetch tree for %s: %s", repo, e)
            return

        files = [
            item for item in tree.get("tree", [])
            if item.get("type") == "blob"
            and item.get("path", "").endswith(ext)
            and self.cfg.min_file_size <= item.get("size", 0) <= self.cfg.max_file_size
        ]

        count = 0
        for item in files:
            if count >= self.cfg.max_files_per_repo:
                break
            content = self._fetch_raw(repo, item["path"])
            if content is None:
                continue
            yield CodeSnippet(
                repo=repo,
                path=item["path"],
                language=language,
                content=content,
                size_bytes=len(content.encode()),
                url=f"https://github.com/{repo}/blob/HEAD/{item['path']}",
            )
            count += 1
            time.sleep(self.cfg.request_delay)

    def _fetch_raw(self, repo: str, path: str) -> str | None:
        """Download raw file content."""
        url = f"https://raw.githubusercontent.com/{repo}/HEAD/{path}"
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            log.debug("Could not fetch %s/%s: %s", repo, path, e)
            return None

    def _get(self, url: str, params: dict | None = None) -> dict:
        """GET with retry on rate-limit (429 / 403)."""
        for attempt in range(3):
            resp = self._client.get(url, params=params)
            if resp.status_code in (429, 403):
                wait = 2 ** attempt * 10
                log.warning("Rate limited. Waiting %ds …", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"Failed to GET {url} after retries")

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
