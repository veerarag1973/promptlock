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


# ---------------------------------------------------------------------------
# Error-path coverage
# ---------------------------------------------------------------------------

@patch(
    "promptlock.commands.pull.find_root",
    side_effect=FileNotFoundError("no .promptlock found"),
)
def test_pull_not_in_project(mock_root, tmp_path: Path):
    """pull exits 1 when not in a promptlock project."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["pull", "prompts/foo.txt"])
    assert result.exit_code != 0


@patch("promptlock.commands.pull.require_token", return_value="tok")
@patch("promptlock.commands.pull.find_root")
def test_pull_no_file_no_all(mock_root, mock_tok, tmp_path: Path):
    """pull without FILE or --all exits 1."""
    mock_root.return_value = tmp_path
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["pull"])
    assert result.exit_code != 0
    assert "--all" in result.output or "provide" in result.output.lower()


@patch("promptlock.commands.pull.RegistryClient")
@patch("promptlock.commands.pull.require_token", return_value="tok")
@patch("promptlock.commands.pull.get_registry_url", return_value="http://localhost:8000")
def test_pull_single_registry_error(mock_url, mock_tok, MockClient, tmp_path: Path):
    """Registry error from get_prompt_by_path exits 1."""
    from promptlock.api.client import RegistryClientError
    client = MagicMock()
    client.get_prompt_by_path.side_effect = RegistryClientError(500, "server error")
    MockClient.return_value = client
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(cli, ["init"], catch_exceptions=False)
        result = runner.invoke(cli, ["pull", "prompts/greeting.txt"])
    assert result.exit_code != 0
    assert "registry error" in result.output.lower()


@patch("promptlock.commands.pull.RegistryClient")
@patch("promptlock.commands.pull.require_token", return_value="tok")
@patch("promptlock.commands.pull.get_registry_url", return_value="http://localhost:8000")
def test_pull_all_registry_error_list_prompts(mock_url, mock_tok, MockClient, tmp_path: Path):
    """Registry error from list_prompts (--all) exits 1."""
    from promptlock.api.client import RegistryClientError
    client = MagicMock()
    client.list_prompts.side_effect = RegistryClientError(500, "server error")
    MockClient.return_value = client
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(cli, ["init"], catch_exceptions=False)
        result = runner.invoke(cli, ["pull", "--all"])
    assert result.exit_code != 0


@patch("promptlock.commands.pull.RegistryClient")
@patch("promptlock.commands.pull.require_token", return_value="tok")
@patch("promptlock.commands.pull.get_registry_url", return_value="http://localhost:8000")
def test_pull_already_up_to_date(mock_url, mock_tok, MockClient, tmp_path: Path):
    """When list_versions returns no items, prompt is 'already up to date'."""
    client = MagicMock()
    client.list_prompts.return_value = {"items": [MOCK_PROMPT], "cursor": None}
    client.list_versions.return_value = {"items": [], "cursor": None}
    MockClient.return_value = client
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(cli, ["init"], catch_exceptions=False)
        result = runner.invoke(cli, ["pull", "--all"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "already up to date" in result.output.lower()


@patch("promptlock.commands.pull.RegistryClient")
@patch("promptlock.commands.pull.require_token", return_value="tok")
@patch("promptlock.commands.pull.get_registry_url", return_value="http://localhost:8000")
def test_pull_version_registry_error(mock_url, mock_tok, MockClient, tmp_path: Path):
    """Registry error from list_versions for a specific prompt is skipped."""
    from promptlock.api.client import RegistryClientError
    client = MagicMock()
    client.get_prompt_by_path.return_value = MOCK_PROMPT
    client.list_versions.side_effect = RegistryClientError(500, "server error")
    MockClient.return_value = client
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(cli, ["init"], catch_exceptions=False)
        result = runner.invoke(cli, ["pull", "prompts/greeting.txt"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "error" in result.output.lower()


@patch("promptlock.commands.pull.RegistryClient")
@patch("promptlock.commands.pull.require_token", return_value="tok")
@patch("promptlock.commands.pull.get_registry_url", return_value="http://localhost:8000")
def test_pull_base64_content(mock_url, mock_tok, MockClient, tmp_path: Path):
    """Version with content_base64 is decoded and written to the object store."""
    import base64
    content_bytes = b"Hello, {{ name }}!"
    version_with_content = {
        **MOCK_VERSION,
        "content_base64": base64.b64encode(content_bytes).decode(),
    }
    client = MagicMock()
    client.get_prompt_by_path.return_value = MOCK_PROMPT
    client.list_versions.return_value = {"items": [version_with_content], "cursor": None}
    MockClient.return_value = client
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(cli, ["init"], catch_exceptions=False)
        result = runner.invoke(cli, ["pull", "prompts/greeting.txt"], catch_exceptions=False)
    assert result.exit_code == 0
