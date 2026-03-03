"""CLI tests for: promptlock validate --env <env> (v0.5)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from promptlock.main import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_project(runner: CliRunner) -> None:
    """Initialise a promptlock project in the current isolated filesystem."""
    runner.invoke(cli, ["init"], catch_exceptions=False)


def _save_prompt(runner: CliRunner, path: str = "prompts/chat.txt") -> None:
    """Save a prompt file and track it."""
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("Hello, {{name}}!")
    runner.invoke(cli, ["save", path, "-m", "initial"], catch_exceptions=False)


# ---------------------------------------------------------------------------
# validate — not in project
# ---------------------------------------------------------------------------

@patch(
    "promptlock.commands.validate.find_root",
    side_effect=FileNotFoundError("no .promptlock found"),
)
def test_validate_not_in_project(mock_find_root, tmp_path: Path):
    """validate fails with exit code 1 when not in a promptlock project."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["validate", "--env", "staging"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# validate — not logged in
# ---------------------------------------------------------------------------

@patch("promptlock.commands.validate.get_token", return_value=None)
def test_validate_not_logged_in(mock_token, tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _init_project(runner)
        result = runner.invoke(cli, ["validate", "--env", "staging"])
    assert result.exit_code != 0
    assert "login" in result.output.lower()


# ---------------------------------------------------------------------------
# validate — no tracked prompts
# ---------------------------------------------------------------------------

@patch("promptlock.commands.validate.get_token", return_value="tok123")
@patch("promptlock.commands.validate.get_registry_url", return_value="http://localhost:8000")
def test_validate_no_tracked_prompts(mock_url, mock_token, tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _init_project(runner)
        result = runner.invoke(cli, ["validate", "--env", "staging"], catch_exceptions=False)
    # Exits 0 (nothing to validate)
    assert result.exit_code == 0
    assert "no prompts" in result.output.lower()


# ---------------------------------------------------------------------------
# validate — all prompts match registry
# ---------------------------------------------------------------------------

@patch("promptlock.commands.validate.get_token", return_value="tok123")
@patch("promptlock.commands.validate.get_registry_url", return_value="http://localhost:8000")
@patch("promptlock.commands.validate.RegistryClient")
def test_validate_all_match(MockClient, mock_url, mock_token, tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _init_project(runner)
        _save_prompt(runner)

        # Get the actual sha256 that was saved
        from promptlock.local.store import get_head, get_version, find_root
        from pathlib import Path as P
        root = P.cwd()
        head = get_head(root, "prompts/chat.txt")
        meta = get_version(root, "prompts/chat.txt", head)
        saved_sha = meta["sha256"]

        # Mock registry returns same SHA
        instance = MockClient.return_value
        instance.get_active_versions.return_value = {
            "environment": "staging",
            "items": [
                {
                    "prompt_path": "prompts/chat.txt",
                    "version_num": head,
                    "sha256": saved_sha,
                    "activated_at": "2026-01-01T00:00:00Z",
                }
            ],
        }

        result = runner.invoke(
            cli, ["validate", "--env", "staging"], catch_exceptions=False
        )

    assert result.exit_code == 0
    assert "valid" in result.output.lower()


# ---------------------------------------------------------------------------
# validate — SHA mismatch (local ≠ registry)
# ---------------------------------------------------------------------------

@patch("promptlock.commands.validate.get_token", return_value="tok123")
@patch("promptlock.commands.validate.get_registry_url", return_value="http://localhost:8000")
@patch("promptlock.commands.validate.RegistryClient")
def test_validate_sha_mismatch(MockClient, mock_url, mock_token, tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _init_project(runner)
        _save_prompt(runner)

        instance = MockClient.return_value
        instance.get_active_versions.return_value = {
            "environment": "staging",
            "items": [
                {
                    "prompt_path": "prompts/chat.txt",
                    "version_num": 1,
                    "sha256": "0000000000000000different",   # deliberately different
                    "activated_at": "2026-01-01T00:00:00Z",
                }
            ],
        }

        result = runner.invoke(cli, ["validate", "--env", "staging"])

    assert result.exit_code != 0
    assert "mismatch" in result.output.lower() or "fail" in result.output.lower()


# ---------------------------------------------------------------------------
# validate — prompt missing from registry
# ---------------------------------------------------------------------------

@patch("promptlock.commands.validate.get_token", return_value="tok123")
@patch("promptlock.commands.validate.get_registry_url", return_value="http://localhost:8000")
@patch("promptlock.commands.validate.RegistryClient")
def test_validate_prompt_missing_from_registry(MockClient, mock_url, mock_token, tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _init_project(runner)
        _save_prompt(runner)

        instance = MockClient.return_value
        instance.get_active_versions.return_value = {
            "environment": "staging",
            "items": [],  # no active versions in registry
        }

        result = runner.invoke(cli, ["validate", "--env", "staging"])

    assert result.exit_code != 0
    assert "missing" in result.output.lower() or "fail" in result.output.lower()


# ---------------------------------------------------------------------------
# validate — registry error
# ---------------------------------------------------------------------------

@patch("promptlock.commands.validate.get_token", return_value="tok123")
@patch("promptlock.commands.validate.get_registry_url", return_value="http://localhost:8000")
@patch("promptlock.commands.validate.RegistryClient")
def test_validate_registry_error(MockClient, mock_url, mock_token, tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _init_project(runner)
        _save_prompt(runner)

        from promptlock.api.client import RegistryClientError
        instance = MockClient.return_value
        instance.get_active_versions.side_effect = RegistryClientError(500, "Internal error")

        result = runner.invoke(cli, ["validate", "--env", "staging"])

    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# validate — JSON output format
# ---------------------------------------------------------------------------

@patch("promptlock.commands.validate.get_token", return_value="tok123")
@patch("promptlock.commands.validate.get_registry_url", return_value="http://localhost:8000")
@patch("promptlock.commands.validate.RegistryClient")
def test_validate_json_format(MockClient, mock_url, mock_token, tmp_path: Path):
    """--format json produces valid JSON output."""
    import json as jsonlib
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _init_project(runner)
        _save_prompt(runner)

        from promptlock.local.store import get_head, get_version
        from pathlib import Path as P
        root = P.cwd()
        head = get_head(root, "prompts/chat.txt")
        meta = get_version(root, "prompts/chat.txt", head)
        saved_sha = meta["sha256"]

        instance = MockClient.return_value
        instance.get_active_versions.return_value = {
            "environment": "staging",
            "items": [{"prompt_path": "prompts/chat.txt", "version_num": head, "sha256": saved_sha, "activated_at": "2026-01-01T00:00:00Z"}],
        }

        result = runner.invoke(
            cli, ["validate", "--env", "staging", "--format", "json"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    # Output should be valid JSON
    data = jsonlib.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["status"] == "ok"
