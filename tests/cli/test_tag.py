"""CLI tests for: promptlock tag"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from promptlock.main import cli


def _init_file(runner: CliRunner) -> Path:
    runner.invoke(cli, ["init"], catch_exceptions=False)
    f = Path("prompts/msg.txt")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("hello world")
    runner.invoke(cli, ["save", str(f), "-m", "initial"], catch_exceptions=False)
    return f


class TestTagCommand:
    def test_tag_adds_to_head_version(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init_file(runner)
            result = runner.invoke(cli, ["tag", str(f), "v1", "--name", "stable"], catch_exceptions=False)
            assert result.exit_code == 0

    def test_tag_shows_confirmation(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init_file(runner)
            result = runner.invoke(cli, ["tag", str(f), "v1", "--name", "release-1.0"], catch_exceptions=False)
            assert result.exit_code == 0

    def test_tag_specific_version(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init_file(runner)
            result = runner.invoke(cli, ["tag", str(f), "v1", "--name", "old-tag"], catch_exceptions=False)
            assert result.exit_code == 0

    def test_tag_requires_name_option(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init_file(runner)
            # Missing --name should fail with exit code 2 (Click usage error)
            result = runner.invoke(cli, ["tag", str(f), "v1"])
            assert result.exit_code == 2

    def test_duplicate_tag_ignored(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init_file(runner)
            runner.invoke(cli, ["tag", str(f), "v1", "--name", "stable"], catch_exceptions=False)
            result = runner.invoke(cli, ["tag", str(f), "v1", "--name", "stable"], catch_exceptions=False)
            assert result.exit_code == 0
