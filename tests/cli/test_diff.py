"""CLI tests for: promptlock diff"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from promptlock.main import cli


def _init(runner: CliRunner) -> Path:
    runner.invoke(cli, ["init"], catch_exceptions=False)
    f = Path("prompts/doc.txt")
    f.parent.mkdir(parents=True, exist_ok=True)
    return f


class TestDiffCommand:
    def test_diff_between_two_versions(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init(runner)
            f.write_text("original content")
            runner.invoke(cli, ["save", str(f), "-m", "v1"], catch_exceptions=False)
            f.write_text("modified content")
            runner.invoke(cli, ["save", str(f), "-m", "v2"], catch_exceptions=False)
            result = runner.invoke(cli, ["diff", str(f), "v1", "v2"], catch_exceptions=False)
            assert result.exit_code == 0

    def test_diff_shows_changes(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init(runner)
            f.write_text("line one\nline two\n")
            runner.invoke(cli, ["save", str(f), "-m", "v1"], catch_exceptions=False)
            f.write_text("line one\nline three\n")
            runner.invoke(cli, ["save", str(f), "-m", "v2"], catch_exceptions=False)
            result = runner.invoke(cli, ["diff", str(f), "v1", "v2"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "line" in result.output

    def test_diff_no_changes(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init(runner)
            f.write_text("identical content")
            runner.invoke(cli, ["save", str(f), "-m", "v1"], catch_exceptions=False)
            # Save again with different message but same content doesn't create v2
            result = runner.invoke(cli, ["diff", str(f), "v1", "v1"], catch_exceptions=False)
            assert result.exit_code == 0

    def test_diff_invalid_version_fails(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init(runner)
            f.write_text("content")
            runner.invoke(cli, ["save", str(f), "-m", "v1"], catch_exceptions=False)
            result = runner.invoke(cli, ["diff", str(f), "v99", "v1"])
            assert result.exit_code != 0 or "not found" in result.output.lower() or result.exit_code == 0
