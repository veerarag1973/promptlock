"""CLI tests for: promptlock save"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from promptlock.main import cli


def _setup(runner: CliRunner) -> Path:
    """Init project and return a prompt file."""
    runner.invoke(cli, ["init"], catch_exceptions=False)
    f = Path("prompts/greeting.txt")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("Hello, {{ name }}!")
    return f


class TestSaveCommand:
    def test_save_creates_new_version(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _setup(runner)
            result = runner.invoke(cli, ["save", str(f), "-m", "first save"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "v1" in result.output

    def test_save_increments_version(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _setup(runner)
            runner.invoke(cli, ["save", str(f), "-m", "first"], catch_exceptions=False)
            f.write_text("Hello, {{ name }}! How are you?")
            result = runner.invoke(cli, ["save", str(f), "-m", "second"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "v2" in result.output

    def test_save_unchanged_content_no_new_version(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _setup(runner)
            runner.invoke(cli, ["save", str(f), "-m", "first"], catch_exceptions=False)
            result = runner.invoke(cli, ["save", str(f), "-m", "same content"], catch_exceptions=False)
            assert result.exit_code == 0
            out = result.output.lower()
            assert "identical" in out or "unchanged" in out or "no changes" in out or "nothing to save" in out

    @patch("promptlock.commands.save.find_root", side_effect=FileNotFoundError("Not a promptlock project"))
    def test_save_outside_project_root_fails(self, mock_find, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = Path("foo.txt")
            f.write_text("hello")
            result = runner.invoke(cli, ["save", str(f), "-m", "test"])
            assert result.exit_code != 0

    def test_save_missing_file_fails(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init"], catch_exceptions=False)
            result = runner.invoke(cli, ["save", "does_not_exist.txt", "-m", "test"])
            assert result.exit_code != 0

    def test_save_with_author(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _setup(runner)
            result = runner.invoke(
                cli,
                ["save", str(f), "-m", "authored", "--author", "alice"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            assert "v1" in result.output
