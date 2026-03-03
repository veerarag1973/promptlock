"""CLI tests for: promptlock rollback"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from promptlock.main import cli


def _init_and_commit(runner: CliRunner, n: int = 2) -> Path:
    runner.invoke(cli, ["init"], catch_exceptions=False)
    f = Path("prompts/note.txt")
    f.parent.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        f.write_text(f"content version {i}")
        runner.invoke(cli, ["save", str(f), "-m", f"v{i}"], catch_exceptions=False)
    return f


class TestRollbackCommand:
    def test_rollback_with_y_flag(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init_and_commit(runner, 2)
            result = runner.invoke(cli, ["rollback", str(f), "v1", "-y"], catch_exceptions=False)
            assert result.exit_code == 0

    def test_rollback_updates_head(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init_and_commit(runner, 2)
            runner.invoke(cli, ["rollback", str(f), "v1", "-y"], catch_exceptions=False)
            from promptlock.local.store import find_root, get_head, _normalize_prompt_path
            root = find_root(Path.cwd())
            key = _normalize_prompt_path(str(f))
            head = get_head(root, key)
            assert head is not None
            assert head == 1

    def test_rollback_with_confirmation_prompt(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init_and_commit(runner, 2)
            result = runner.invoke(cli, ["rollback", str(f), "v1"], input="y\n")
            assert result.exit_code == 0

    def test_rollback_aborted(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init_and_commit(runner, 2)
            result = runner.invoke(cli, ["rollback", str(f), "v1"], input="n\n")
            # click.confirm(abort=True) raises Abort on 'n', which Click treats as exit code 1
            assert result.exit_code != 0 or "abort" in result.output.lower()

    def test_rollback_invalid_version_fails(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            f = _init_and_commit(runner, 1)
            result = runner.invoke(cli, ["rollback", str(f), "v99", "-y"])
            assert result.exit_code != 0 or "not found" in result.output.lower()
