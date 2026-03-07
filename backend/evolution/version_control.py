"""
VersionControl – tag successful agent configurations in Git.

Successful configs are serialised to JSON and stored under
  evolution/configs/<tag>.json
then a lightweight Git tag is created so the full config history is
browsable via `git tag -l 'evo-*'`.

Usage
-----
    from evolution.version_control import VersionControl

    vc = VersionControl()
    tag = vc.save_config(
        "nvidia-prompt-v3",
        config={"provider": "nvidia", "system_prompt": "...", "score": 0.92},
        message="Best prompt after 200 runs",
    )
    # -> "evo-nvidia-prompt-v3-20260307T1430"

    all_tags = vc.list_configs()
    cfg = vc.load_config("evo-nvidia-prompt-v3-20260307T1430")
"""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONFIGS_DIR = Path(__file__).parent / "configs"


class VersionControl:
    def __init__(
        self,
        configs_dir: Path | str = CONFIGS_DIR,
        repo_root: Path | str | None = None,
    ) -> None:
        self.configs_dir = Path(configs_dir)
        self.configs_dir.mkdir(parents=True, exist_ok=True)
        self.repo_root = Path(repo_root) if repo_root else self._find_repo_root()

    # ── Config persistence ─────────────────────────────────────────────────────

    def save_config(
        self,
        name: str,
        config: dict[str, Any],
        *,
        message: str = "",
        tag: bool = True,
    ) -> str:
        """
        Write config JSON and create a Git tag.

        Returns the tag name (or file stem if tagging is skipped/fails).
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
        tag_name = f"evo-{name}-{ts}"

        payload = {
            "tag":       tag_name,
            "name":      name,
            "saved_at":  time.time(),
            "message":   message,
            "config":    config,
        }
        file_path = self.configs_dir / f"{tag_name}.json"
        file_path.write_text(json.dumps(payload, indent=2))

        if tag:
            self._git_tag(tag_name, message or f"Evolution config: {name}")

        return tag_name

    def load_config(self, tag_name: str) -> dict[str, Any]:
        """Load a previously saved config by tag name."""
        file_path = self.configs_dir / f"{tag_name}.json"
        if not file_path.exists():
            raise FileNotFoundError(f"Config '{tag_name}' not found at {file_path}")
        return json.loads(file_path.read_text())

    def list_configs(self) -> list[dict[str, Any]]:
        """Return metadata for all saved configs, newest first."""
        results = []
        for f in sorted(self.configs_dir.glob("evo-*.json"), reverse=True):
            try:
                data = json.loads(f.read_text())
                results.append({
                    "tag":      data.get("tag", f.stem),
                    "name":     data.get("name", ""),
                    "saved_at": data.get("saved_at", 0),
                    "message":  data.get("message", ""),
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return results

    # ── Git helpers ────────────────────────────────────────────────────────────

    def _git_tag(self, tag_name: str, message: str) -> bool:
        """Create annotated git tag; returns True on success."""
        try:
            subprocess.run(
                ["git", "tag", "-a", tag_name, "-m", message],
                cwd=self.repo_root,
                capture_output=True,
                check=True,
                timeout=15,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def list_git_tags(self) -> list[str]:
        """Return all evo-* git tags in the repo."""
        try:
            result = subprocess.run(
                ["git", "tag", "-l", "evo-*"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            return [t.strip() for t in result.stdout.splitlines() if t.strip()]
        except Exception:
            return []

    @staticmethod
    def _find_repo_root() -> Path:
        """Walk up from this file to find the .git directory."""
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / ".git").exists():
                return parent
        return Path.cwd()
