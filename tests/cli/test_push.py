"""CLI tests for: promptlock push"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from promptlock.main import cli


def _init_with_version(runner: CliRunner) -> Path:
    runner.invoke(cli, ["init"], catch_exceptions=False)
    f = Path("prompts/push_test.txt")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("push me to the cloud")
    runner.invoke(cli, ["save", str(f), "-m", "initial"], catch_exceptions=False)
    return f


def _mock_client():
    client = MagicMock()
    client.create_prompt.return_value = {"id": "prompt_uuid_1", "name": "push_test"}
    client.push_version.return_value = {"id": "ver_1", "version_num": 1}
    return client


@patch("promptlock.commands.push.RegistryClient")
@patch("promptlock.commands.push.require_token", return_value="tok")
@patch("promptlock.commands.push.get_registry_url", return_value="http://localhost:8000")
def test_push_single_version(mock_url, mock_tok, MockClient, tmp_path: Path, monkeypatch):
    MockClient.return_value = _mock_client()
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        f = _init_with_version(runner)
        result = runner.invoke(cli, ["push", str(f)], catch_exceptions=False)
        assert result.exit_code == 0


@patch("promptlock.commands.push.RegistryClient")
@patch("promptlock.commands.push.require_token", return_value="tok")
@patch("promptlock.commands.push.get_registry_url", return_value="http://localhost:8000")
def test_push_all(mock_url, mock_tok, MockClient, tmp_path: Path):
    MockClient.return_value = _mock_client()
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(cli, ["init"], catch_exceptions=False)
        for name in ["a.txt", "b.txt"]:
            f = Path(f"prompts/{name}")
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(f"content of {name}")
            runner.invoke(cli, ["save", str(f), "-m", f"save {name}"], catch_exceptions=False)
        result = runner.invoke(cli, ["push", "--all"], catch_exceptions=False)
        assert result.exit_code == 0


@patch("promptlock.commands.push.RegistryClient")
@patch("promptlock.commands.push.require_token", return_value="tok")
@patch("promptlock.commands.push.get_registry_url", return_value="http://localhost:8000")
def test_push_409_idempotent(mock_url, mock_tok, MockClient, tmp_path: Path):
    """409 Conflict should be treated as success (already pushed)."""
    from promptlock.api.client import RegistryClientError
    client = MagicMock()
    client.create_prompt.return_value = {"id": "prompt_uuid_1", "name": "push_test"}
    client.push_version.side_effect = RegistryClientError(409, "already exists")
    MockClient.return_value = client

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        f = _init_with_version(runner)
        result = runner.invoke(cli, ["push", str(f)], catch_exceptions=False)
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Error-path coverage
# ---------------------------------------------------------------------------

@patch(
    "promptlock.commands.push.find_root",
    side_effect=FileNotFoundError("no .promptlock found"),
)
def test_push_not_in_project(mock_root, tmp_path: Path):
    """push exits 1 when not in a promptlock project."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["push", "prompts/foo.txt"])
    assert result.exit_code != 0


@patch("promptlock.commands.push.RegistryClient")
@patch("promptlock.commands.push.require_token", return_value="tok")
@patch("promptlock.commands.push.get_registry_url", return_value="http://localhost:8000")
@patch("promptlock.commands.push.get_index", return_value={})
@patch("promptlock.commands.push.find_root")
def test_push_all_no_tracked_prompts(mock_root, mock_index, mock_url, mock_tok, MockClient, tmp_path: Path):
    """push --all exits 0 with a warning when there are no tracked prompts."""
    mock_root.return_value = tmp_path
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["push", "--all"])
    assert result.exit_code == 0
    assert "no tracked" in result.output.lower()


@patch("promptlock.commands.push.require_token", return_value="tok")
@patch("promptlock.commands.push.find_root")
def test_push_no_file_and_no_all(mock_root, mock_tok, tmp_path: Path):
    """push without FILE or --all exits 1."""
    mock_root.return_value = tmp_path
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["push"])
    assert result.exit_code != 0
    assert "--all" in result.output or "provide" in result.output.lower()


@patch("promptlock.commands.push.RegistryClient")
@patch("promptlock.commands.push.require_token", return_value="tok")
@patch("promptlock.commands.push.get_registry_url", return_value="http://localhost:8000")
def test_push_registry_error_creating_prompt(mock_url, mock_tok, MockClient, tmp_path: Path):
    """Registry error when creating a prompt resource skips that prompt."""
    from promptlock.api.client import RegistryClientError
    client = MagicMock()
    client.get_prompt_by_path.return_value = None
    client.create_prompt.side_effect = RegistryClientError(500, "internal server error")
    MockClient.return_value = client

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        f = _init_with_version(runner)
        result = runner.invoke(cli, ["push", "--all"])
    assert result.exit_code == 0
    assert "registry error" in result.output.lower()


@patch("promptlock.commands.push.RegistryClient")
@patch("promptlock.commands.push.require_token", return_value="tok")
@patch("promptlock.commands.push.get_registry_url", return_value="http://localhost:8000")
def test_push_non_409_version_error(mock_url, mock_tok, MockClient, tmp_path: Path):
    """Non-409 push_version error is logged but push continues."""
    from promptlock.api.client import RegistryClientError
    client = MagicMock()
    client.get_prompt_by_path.return_value = None
    client.create_prompt.return_value = {"id": "pid", "name": "push_test"}
    client.push_version.side_effect = RegistryClientError(500, "server error")
    MockClient.return_value = client

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        f = _init_with_version(runner)
        result = runner.invoke(cli, ["push", "--all"])
    assert result.exit_code == 0
    assert "error" in result.output.lower()
