"""CLI tests for: promptlock pull"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from promptlock.main import cli


MOCK_PROMPT = {"id": "p1", "name": "greeting", "path": "prompts/greeting.txt"}
MOCK_VERSION = {
    "id": "v1",
    "version_num": 1,
    "sha256": "abc123",
    "message": "initial",
    "template": "Hello, {{ name }}!",
    "tags": [],
    "environment": "development",
    "author": "alice",
    "created_at": "2024-01-01T00:00:00",
}
MOCK_VERSIONS_RESPONSE = {"items": [MOCK_VERSION], "cursor": None}


def _mock_client():
    client = MagicMock()
    client.get_prompt_by_path.return_value = MOCK_PROMPT
    client.list_versions.return_value = MOCK_VERSIONS_RESPONSE
    client.get_version.return_value = MOCK_VERSION
    client.list_prompts.return_value = {"items": [MOCK_PROMPT], "cursor": None}
    return client


@patch("promptlock.commands.pull.RegistryClient")
@patch("promptlock.commands.pull.require_token", return_value="tok")
@patch("promptlock.commands.pull.get_registry_url", return_value="http://localhost:8000")
def test_pull_single_prompt(mock_url, mock_tok, MockClient, tmp_path: Path):
    MockClient.return_value = _mock_client()
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(cli, ["init"], catch_exceptions=False)
        result = runner.invoke(cli, ["pull", "prompts/greeting.txt"], catch_exceptions=False)
        assert result.exit_code == 0


@patch("promptlock.commands.pull.RegistryClient")
@patch("promptlock.commands.pull.require_token", return_value="tok")
@patch("promptlock.commands.pull.get_registry_url", return_value="http://localhost:8000")
def test_pull_all(mock_url, mock_tok, MockClient, tmp_path: Path):
    MockClient.return_value = _mock_client()
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(cli, ["init"], catch_exceptions=False)
        result = runner.invoke(cli, ["pull", "--all"], catch_exceptions=False)
        assert result.exit_code == 0


@patch("promptlock.commands.pull.RegistryClient")
@patch("promptlock.commands.pull.require_token", return_value="tok")
@patch("promptlock.commands.pull.get_registry_url", return_value="http://localhost:8000")
def test_pull_not_found(mock_url, mock_tok, MockClient, tmp_path: Path):
    from promptlock.api.client import RegistryClientError
    client = MagicMock()
    client.get_prompt_by_path.return_value = None
    MockClient.return_value = client
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(cli, ["init"], catch_exceptions=False)
        result = runner.invoke(cli, ["pull", "prompts/missing.txt"])
        assert result.exit_code != 0 or "not found" in result.output.lower()


@patch("promptlock.commands.pull.RegistryClient")
@patch("promptlock.commands.pull.require_token", return_value="tok")
@patch("promptlock.commands.pull.get_registry_url", return_value="http://localhost:8000")
def test_pull_updates_local_store(mock_url, mock_tok, MockClient, tmp_path: Path):
    """Pull should update HEAD in the local store even if no disk file is written."""
    MockClient.return_value = _mock_client()
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(cli, ["init"], catch_exceptions=False)
        result = runner.invoke(cli, ["pull", "prompts/greeting.txt"], catch_exceptions=False)
        assert result.exit_code == 0
        # HEAD should be updated in the local store
        from promptlock.local.store import find_root, get_head
        root = find_root(Path.cwd())
        head = get_head(root, "prompts/greeting.txt")
        # head should be the version_num (1) after pull
        assert head == 1
