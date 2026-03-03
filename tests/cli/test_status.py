"""CLI tests for: promptlock status"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from promptlock.main import cli


def _setup_prompt(runner: CliRunner, content: str = "initial content") -> Path:
    runner.invoke(cli, ["init"], catch_exceptions=False)
    f = Path("prompts/status_test.txt")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    runner.invoke(cli, ["save", str(f), "-m", "first"], catch_exceptions=False)
    return f


class TestStatusCommand:
    def test_status_clean(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _setup_prompt(runner)
            result = runner.invoke(cli, ["status"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "clean" in result.output.lower()

    def test_status_modified(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _setup_prompt(runner)
            f.write_text("modified content")
            result = runner.invoke(cli, ["status"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "modified" in result.output.lower()

    def test_status_missing(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _setup_prompt(runner)
            f.unlink()
            result = runner.invoke(cli, ["status"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "missing" in result.output.lower()

    def test_status_never_saved(self, tmp_path: Path):
        """Running status in a project with no tracked files should succeed."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init"], catch_exceptions=False)
            result = runner.invoke(cli, ["status"], catch_exceptions=False)
            assert result.exit_code == 0

    @patch("promptlock.commands.status.find_root", side_effect=FileNotFoundError("Not a promptlock project"))
    def test_status_outside_project_fails(self, mock_find, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["status"])
            assert result.exit_code != 0
