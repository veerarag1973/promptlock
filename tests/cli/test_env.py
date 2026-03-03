"""CLI tests for: promptlock env list"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from promptlock.main import cli


FULL_TOML = """\
[environments]
default = "development"

[environments.development]
model = "claude-3-5-sonnet"

[environments.staging]
model = "claude-3-5-sonnet"

[environments.production]
model = "claude-3-opus"
"""

MOCK_ENVS = {
    "items": [
        {"id": "e1", "name": "development", "type": "builtin"},
        {"id": "e2", "name": "staging", "type": "builtin"},
        {"id": "e3", "name": "production", "type": "builtin"},
    ],
    "cursor": None,
}


class TestEnvListCommand:
    def test_env_list_reads_toml(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init"], catch_exceptions=False)
            Path(".promptlock.toml").write_text(FULL_TOML, encoding="utf-8")
            result = runner.invoke(cli, ["env", "list"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "development" in result.output

    def test_env_list_shows_all_environments(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init"], catch_exceptions=False)
            Path(".promptlock.toml").write_text(FULL_TOML, encoding="utf-8")
            result = runner.invoke(cli, ["env", "list"], catch_exceptions=False)
            assert "staging" in result.output
            assert "production" in result.output

    @patch("promptlock.api.client.RegistryClient")
    @patch("promptlock.auth.get_token", return_value="tok")
    @patch("promptlock.auth.get_registry_url", return_value="http://localhost:8000")
    def test_env_list_remote(self, mock_url, mock_tok, MockClient, tmp_path: Path):
        client = MagicMock()
        client.list_environments.return_value = MOCK_ENVS
        MockClient.return_value = client
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init"], catch_exceptions=False)
            result = runner.invoke(cli, ["env", "list", "--remote"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "development" in result.output

    @patch("promptlock.commands.env.find_root", side_effect=FileNotFoundError("Not a promptlock project"))
    def test_env_list_no_project_fails(self, mock_find, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["env", "list"])
            assert result.exit_code != 0
