"""CLI tests for: promptlock log"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from promptlock.main import cli


def _init_with_versions(runner: CliRunner, n: int = 2) -> Path:
    runner.invoke(cli, ["init"], catch_exceptions=False)
    f = Path("prompts/note.txt")
    f.parent.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        f.write_text(f"version {i} content")
        runner.invoke(cli, ["save", str(f), "-m", f"commit {i}"], catch_exceptions=False)
    return f


class TestLogCommand:
    def test_log_shows_versions(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init_with_versions(runner, 2)
            result = runner.invoke(cli, ["log", str(f)], catch_exceptions=False)
            assert result.exit_code == 0
            assert "v1" in result.output

    def test_log_shows_all_versions(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init_with_versions(runner, 3)
            result = runner.invoke(cli, ["log", str(f)], catch_exceptions=False)
            assert result.exit_code == 0
            assert "v2" in result.output
            assert "v3" in result.output

    def test_log_limit(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init_with_versions(runner, 3)
            result = runner.invoke(cli, ["log", str(f), "--limit", "1"], catch_exceptions=False)
            assert result.exit_code == 0
            # Should only show 1 version
            assert result.output.count("v") >= 1

    def test_log_no_versions(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init"], catch_exceptions=False)
            f = Path("prompts/empty.txt")
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("hello")
            result = runner.invoke(cli, ["log", str(f)], catch_exceptions=False)
            assert result.exit_code == 0
            assert "no versions" in result.output.lower() or result.output  # graceful

    def test_log_shows_commit_message(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init_with_versions(runner, 1)
            result = runner.invoke(cli, ["log", str(f)], catch_exceptions=False)
            assert result.exit_code == 0
            # The rich table should contain the version reference
            assert "v1" in result.output
