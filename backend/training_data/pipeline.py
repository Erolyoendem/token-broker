"""
Main orchestration pipeline.

Ties together crawler → synthesizer → validator → quality_filter → dataset.

Also sets up APScheduler jobs:
  - Daily:  crawl new snippets + synthesize
  - Weekly: log difficult patterns + prompt-optimisation hints
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from .crawler import CrawlerConfig, GitHubCrawler
from .dataset import DatasetManager, TrainingPair
from .language_pairs import LANGUAGE_PAIRS, LanguagePair, get_pair
from .quality_filter import MultiAgentFilter
from .synthesizer import Synthesizer
from .validator import Validator

log = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    proxy_url: str = "http://localhost:8000"
    api_key: str = ""
    github_token: str = ""
    discord_webhook: str = ""
    max_repos: int = 3
    max_files_per_repo: int = 5
    run_quality_filter: bool = True
    # pair IDs to process; None = all registered pairs
    pair_ids: Optional[list[str]] = None


@dataclass
class RunStats:
    crawled: int = 0
    synthesized: int = 0
    validated_ok: int = 0
    accepted: int = 0
    rejected: int = 0
    review: int = 0
    tokens_used: int = 0
    errors: list[str] = field(default_factory=list)


class TrainingPipeline:
    def __init__(self, config: PipelineConfig, db_client=None):
        self.cfg = config
        self._synthesizer = Synthesizer(
            proxy_url=config.proxy_url,
            api_key=config.api_key,
        )
        self._validator = Validator()
        self._filter = MultiAgentFilter(
            proxy_url=config.proxy_url,
            api_key=config.api_key,
            discord_webhook=config.discord_webhook,
        )
        self._dataset = DatasetManager(db_client)
        self._scheduler: Optional[BackgroundScheduler] = None

    # ── Public ────────────────────────────────────────────────────────────────

    def run_once(self, pair_id: str) -> RunStats:
        """Run a full pipeline pass for one language pair."""
        pair = get_pair(pair_id)
        stats = RunStats()

        crawler_cfg = CrawlerConfig(
            github_token=self.cfg.github_token,
            max_repos=self.cfg.max_repos,
            max_files_per_repo=self.cfg.max_files_per_repo,
        )

        with GitHubCrawler(crawler_cfg) as crawler:
            for snippet in crawler.crawl_seed_repos(pair.source_lang):
                stats.crawled += 1
                try:
                    result = self._process_snippet(snippet.content, snippet.url, pair, stats)
                    if result:
                        stats.synthesized += 1
                except Exception as e:
                    log.error("Snippet error (%s): %s", snippet.path, e)
                    stats.errors.append(str(e))

        log.info(
            "[%s] crawled=%d synthesized=%d accepted=%d review=%d tokens=%d",
            pair_id, stats.crawled, stats.synthesized,
            stats.accepted, stats.review, stats.tokens_used,
        )
        return stats

    def run_all_pairs(self) -> dict[str, RunStats]:
        """Run the pipeline for all configured language pairs."""
        pair_ids = self.cfg.pair_ids or list(LANGUAGE_PAIRS)
        return {pid: self.run_once(pid) for pid in pair_ids}

    def start_scheduler(self) -> None:
        """Start background jobs: daily crawl + weekly analysis."""
        self._scheduler = BackgroundScheduler()
        self._scheduler.add_job(
            self._daily_job, "cron", hour=3, minute=0,
            id="daily_crawl", replace_existing=True,
        )
        self._scheduler.add_job(
            self._weekly_job, "cron", day_of_week="mon", hour=4, minute=0,
            id="weekly_analysis", replace_existing=True,
        )
        self._scheduler.start()
        log.info("TrainingPipeline scheduler started (daily 03:00, weekly Mon 04:00)")

    def stop_scheduler(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _process_snippet(
        self,
        source_code: str,
        source_url: str,
        pair: LanguagePair,
        stats: RunStats,
    ) -> bool:
        # Synthesize
        synth = self._synthesizer.synthesize(source_code, pair)
        stats.tokens_used += synth.tokens_used

        # Validate
        score = self._validator.validate_pair(source_code, synth.target_code, pair)
        if score.syntax_ok:
            stats.validated_ok += 1

        # Quality filter (multi-agent)
        if self.cfg.run_quality_filter:
            consensus = self._filter.evaluate_sync(
                source_code, synth.target_code, pair.pair_id
            )
            if consensus.requires_human:
                status = "review"
                stats.review += 1
            elif consensus.accepted:
                status = "accepted"
                stats.accepted += 1
            else:
                status = "rejected"
                stats.rejected += 1
            agent_ratings = consensus.ratings
        else:
            status = "accepted" if score.confidence >= 0.7 else "review"
            agent_ratings = []
            if status == "accepted":
                stats.accepted += 1
            else:
                stats.review += 1

        # Persist
        self._dataset.insert(TrainingPair(
            pair_id=pair.pair_id,
            source_lang=pair.source_lang,
            target_lang=pair.target_lang,
            source_code=source_code,
            target_code=synth.target_code,
            source_url=source_url,
            tokens_used=synth.tokens_used,
            provider=synth.provider,
            quality_score=score.confidence,
            agent_ratings=agent_ratings,
            status=status,
        ))
        return True

    def _daily_job(self) -> None:
        log.info("Daily crawl starting …")
        try:
            self.run_all_pairs()
        except Exception as e:
            log.error("Daily job failed: %s", e)

    def _weekly_job(self) -> None:
        """Log difficult patterns and prompt-improvement hints."""
        log.info("Weekly analysis starting …")
        try:
            difficult = self._dataset.difficult_patterns(threshold=0.6, limit=10)
            if difficult:
                log.info(
                    "Found %d difficult patterns (score < 0.60). "
                    "Consider adding targeted examples for: %s",
                    len(difficult),
                    {d["pair_id"] for d in difficult},
                )
            stats = self._dataset.stats()
            log.info("Dataset stats: %s", stats)
        except Exception as e:
            log.error("Weekly analysis failed: %s", e)


# ── Factory helper ────────────────────────────────────────────────────────────

def build_pipeline(db_client=None) -> TrainingPipeline:
    """Build a pipeline from environment variables."""
    cfg = PipelineConfig(
        proxy_url=os.getenv("TOKENBROKER_URL", "http://localhost:8000"),
        api_key=os.getenv("TOKENBROKER_KEY", ""),
        github_token=os.getenv("GITHUB_TOKEN", ""),
        discord_webhook=os.getenv("DISCORD_WEBHOOK_URL", ""),
        max_repos=int(os.getenv("PIPELINE_MAX_REPOS", "3")),
        max_files_per_repo=int(os.getenv("PIPELINE_MAX_FILES", "5")),
        run_quality_filter=os.getenv("PIPELINE_QUALITY_FILTER", "true").lower() == "true",
    )
    return TrainingPipeline(cfg, db_client)
