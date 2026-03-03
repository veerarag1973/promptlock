"""CLI tests for: promptlock promote"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from promptlock.main import cli


MOCK_PROMOTION = {
    "id": "pr1",
    "status": "approved",
    "from_environment": "development",
    "to_environment": "staging",
    "version_num": 1,
}


def _init_with_version(runner: CliRunner) -> Path:
    runner.invoke(cli, ["init"], catch_exceptions=False)
    f = Path("prompts/promote_test.txt")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("test prompt for promotion")
    runner.invoke(cli, ["save", str(f), "-m", "initial"], catch_exceptions=False)
    return f


class TestPromoteCommand:
    @patch("promptlock.api.client.RegistryClient")
    @patch("promptlock.auth.get_token", return_value="tok")
    @patch("promptlock.auth.get_registry_url", return_value="http://localhost:8000")
    def test_promote_head_version(self, mock_url, mock_tok, MockClient, tmp_path: Path):
        client = MagicMock()
        client.create_promotion.return_value = MOCK_PROMOTION
        MockClient.return_value = client
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init_with_version(runner)
            result = runner.invoke(
                cli,
                ["promote", str(f), "--from", "development", "--to", "staging"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0

    @patch("promptlock.api.client.RegistryClient")
    @patch("promptlock.auth.get_token", return_value="tok")
    @patch("promptlock.auth.get_registry_url", return_value="http://localhost:8000")
    def test_promote_specific_version(self, mock_url, mock_tok, MockClient, tmp_path: Path):
        client = MagicMock()
        client.create_promotion.return_value = MOCK_PROMOTION
        MockClient.return_value = client
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init_with_version(runner)
            result = runner.invoke(
                cli,
                ["promote", str(f), "--from", "development", "--to", "staging", "--version", "v1"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0

    @patch("promptlock.api.client.RegistryClient")
    @patch("promptlock.auth.get_token", return_value="tok")
    @patch("promptlock.auth.get_registry_url", return_value="http://localhost:8000")
    def test_promote_writes_promotions_jsonl(self, mock_url, mock_tok, MockClient, tmp_path: Path):
        import json
        client = MagicMock()
        client.create_promotion.return_value = MOCK_PROMOTION
        MockClient.return_value = client
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init_with_version(runner)
            runner.invoke(
                cli,
                ["promote", str(f), "--from", "development", "--to", "staging"],
                catch_exceptions=False,
            )
            promotions_file = Path(".promptlock/promotions.jsonl")
            assert promotions_file.exists()
            lines = [json.loads(l) for l in promotions_file.read_text().splitlines() if l.strip()]
            assert len(lines) >= 1

    @patch("promptlock.commands.promote.find_root", side_effect=FileNotFoundError("Not a promptlock project"))
    def test_promote_no_project_fails(self, mock_find, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                ["promote", "prompts/foo.txt", "--from", "dev", "--to", "staging"],
            )
            assert result.exit_code != 0

    @patch("promptlock.api.client.RegistryClient")
    @patch("promptlock.auth.get_token", return_value="tok")
    @patch("promptlock.auth.get_registry_url", return_value="http://localhost:8000")
    def test_promote_no_head_fails(self, mock_url, mock_tok, MockClient, tmp_path: Path):
        client = MagicMock()
        MockClient.return_value = client
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init"], catch_exceptions=False)
            # File exists but never saved
            f = Path("prompts/unsaved.txt")
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("content")
            result = runner.invoke(
                cli,
                ["promote", str(f), "--from", "development", "--to", "staging"],
            )
            assert result.exit_code != 0
