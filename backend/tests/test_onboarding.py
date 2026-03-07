"""Tests fuer das Zero-Cost-Onboarding-System (TAB 14)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent.parent
ONBOARDING_DIR = PROJECT_ROOT / "docs" / "onboarding"
CONFIG_FILE = PROJECT_ROOT / "project_config.yaml"


# ---------------------------------------------------------------------------
# Dokumentations-Dateien
# ---------------------------------------------------------------------------


def test_project_summary_exists():
    assert (ONBOARDING_DIR / "PROJECT_SUMMARY.md").exists(), "PROJECT_SUMMARY.md fehlt"


def test_next_tasks_exists():
    assert (ONBOARDING_DIR / "NEXT_TASKS.md").exists(), "NEXT_TASKS.md fehlt"


def test_context_exists():
    assert (ONBOARDING_DIR / "CONTEXT.md").exists(), "CONTEXT.md fehlt"


def test_project_summary_has_content():
    content = (ONBOARDING_DIR / "PROJECT_SUMMARY.md").read_text()
    assert "TokenBroker" in content
    assert len(content) > 200


def test_context_has_architecture_section():
    content = (ONBOARDING_DIR / "CONTEXT.md").read_text()
    assert "Architektur" in content or "architecture" in content.lower()


def test_next_tasks_has_prioritized_items():
    content = (ONBOARDING_DIR / "NEXT_TASKS.md").read_text()
    assert "Prioritaet" in content or "Priorität" in content or "priority" in content.lower()


# ---------------------------------------------------------------------------
# project_config.yaml
# ---------------------------------------------------------------------------


def test_config_file_exists():
    assert CONFIG_FILE.exists(), "project_config.yaml fehlt"


def test_config_is_valid_yaml():
    data = yaml.safe_load(CONFIG_FILE.read_text())
    assert isinstance(data, dict)


def test_config_has_required_keys():
    data = yaml.safe_load(CONFIG_FILE.read_text())
    assert "project" in data
    assert "technologies" in data
    assert "important_files" in data
    assert "environment_variables" in data


def test_config_project_fields():
    data = yaml.safe_load(CONFIG_FILE.read_text())
    project = data["project"]
    assert "name" in project
    assert "repository" in project
    assert project["name"] == "TokenBroker"


def test_config_env_vars_listed():
    data = yaml.safe_load(CONFIG_FILE.read_text())
    required = data["environment_variables"]["required"]
    assert "NVIDIA_API_KEY" in required
    assert "DEEPSEEK_API_KEY" in required
    assert "SUPABASE_URL" in required


# ---------------------------------------------------------------------------
# ContextGenerator
# ---------------------------------------------------------------------------


def test_context_generator_imports():
    from onboarding.context_generator import ContextGenerator
    assert ContextGenerator is not None


def test_context_generator_instantiation():
    from onboarding.context_generator import ContextGenerator
    gen = ContextGenerator()
    assert gen is not None
    assert isinstance(gen.generated_at, str)


def test_context_generator_analyze_structure():
    from onboarding.context_generator import ContextGenerator
    gen = ContextGenerator()
    structure = gen.analyze_structure()
    assert isinstance(structure, dict)
    assert "backend" in structure


def test_context_generator_get_open_todos():
    from onboarding.context_generator import ContextGenerator
    gen = ContextGenerator()
    todos = gen.get_open_todos()
    assert isinstance(todos, list)


def test_context_generator_build_snapshot():
    from onboarding.context_generator import ContextGenerator
    gen = ContextGenerator()
    snapshot = gen.build_snapshot()
    assert "generated_at" in snapshot
    assert "project" in snapshot
    assert "recent_commits" in snapshot
    assert "open_todos" in snapshot
    assert "structure" in snapshot
    assert "onboarding_docs" in snapshot


def test_context_generator_snapshot_has_docs():
    from onboarding.context_generator import ContextGenerator
    gen = ContextGenerator()
    snapshot = gen.build_snapshot()
    docs = snapshot["onboarding_docs"]
    assert "summary" in docs
    assert "context" in docs
    assert "next_tasks" in docs
    # Inhalte sollten nicht leer sein
    assert len(docs["summary"]) > 50
    assert len(docs["context"]) > 50


# ---------------------------------------------------------------------------
# OnboardingPromptGenerator
# ---------------------------------------------------------------------------


def test_prompt_generator_imports():
    from onboarding.context_generator import OnboardingPromptGenerator
    assert OnboardingPromptGenerator is not None


def test_prompt_generator_general():
    from onboarding.context_generator import OnboardingPromptGenerator
    gen = OnboardingPromptGenerator()
    prompt = gen.generate()
    assert "TokenBroker" in prompt
    assert len(prompt) > 500


def test_prompt_generator_with_keyword_payment():
    from onboarding.context_generator import OnboardingPromptGenerator
    gen = OnboardingPromptGenerator()
    prompt = gen.generate("payment")
    assert "payment" in prompt.lower()
    assert "TokenBroker" in prompt


def test_prompt_generator_with_keyword_crowdfunding():
    from onboarding.context_generator import OnboardingPromptGenerator
    gen = OnboardingPromptGenerator()
    prompt = gen.generate("crowdfunding")
    assert "crowdfunding" in prompt.lower()


def test_prompt_generator_contains_commits():
    from onboarding.context_generator import OnboardingPromptGenerator
    gen = OnboardingPromptGenerator()
    prompt = gen.generate()
    # Prompt sollte Commit-Referenzen enthalten (sofern Git vorhanden)
    assert "Commits" in prompt or "commit" in prompt.lower()


def test_prompt_generator_contains_live_url():
    from onboarding.context_generator import OnboardingPromptGenerator
    gen = OnboardingPromptGenerator()
    prompt = gen.generate()
    assert "railway.app" in prompt or "yondem-production" in prompt


def test_prompt_generator_save(tmp_path):
    from onboarding.context_generator import OnboardingPromptGenerator
    gen = OnboardingPromptGenerator()
    out = tmp_path / "test_prompt.md"
    saved = gen.save_prompt("payment", output_path=out)
    assert saved == out
    assert out.exists()
    assert len(out.read_text()) > 200


# ---------------------------------------------------------------------------
# Keyword-Map
# ---------------------------------------------------------------------------


def test_keyword_map_covers_main_topics():
    from onboarding.context_generator import KEYWORD_MAP
    required_topics = {"payment", "crowdfunding", "auth", "provider", "evolution", "swarm", "market", "tenant"}
    assert required_topics.issubset(set(KEYWORD_MAP.keys()))


# ---------------------------------------------------------------------------
# Discord Bot
# ---------------------------------------------------------------------------


def test_discord_bot_imports():
    from onboarding.discord_bot import greet_new_instance, notify_tab_complete, post_context_summary
    assert greet_new_instance is not None
    assert notify_tab_complete is not None
    assert post_context_summary is not None


def test_discord_bot_no_webhook_returns_false():
    from onboarding.discord_bot import greet_new_instance
    # Ohne Webhook-URL muss False zurueckgegeben werden
    result = greet_new_instance(keyword="test", webhook_url="")
    assert result is False


def test_discord_notify_tab_complete_no_webhook():
    from onboarding.discord_bot import notify_tab_complete
    result = notify_tab_complete("TAB 14", "Zero-Cost-Onboarding", webhook_url="")
    assert result is False


@patch("onboarding.discord_bot.httpx.post")
def test_discord_send_success(mock_post):
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_post.return_value = mock_response

    from onboarding.discord_bot import notify_tab_complete
    result = notify_tab_complete("TAB 14", "Test", webhook_url="https://discord.com/api/webhooks/fake")
    assert result is True
    mock_post.assert_called_once()
