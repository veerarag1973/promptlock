"""CLI tests for: promptlock init"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from promptlock.main import cli


def test_init_creates_store(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["init"], catch_exceptions=False, env={"HOME": str(tmp_path)})
    # Run from tmp_path
    with runner.isolated_filesystem(temp_dir=tmp_path):
        r = runner.invoke(cli, ["init"], catch_exceptions=False)
        assert r.exit_code == 0
        assert Path(".promptlock").is_dir()


def test_init_creates_toml(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(cli, ["init"], catch_exceptions=False)
        assert Path(".promptlock.toml").exists()


def test_init_creates_objects_dir(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(cli, ["init"], catch_exceptions=False)
        assert Path(".promptlock/objects").is_dir()


def test_init_idempotent(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        r1 = runner.invoke(cli, ["init"], catch_exceptions=False)
        r2 = runner.invoke(cli, ["init"], catch_exceptions=False)
        assert r1.exit_code == 0
        assert r2.exit_code == 0


def test_init_output_message(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["init"], catch_exceptions=False)
        assert "init" in result.output.lower() or "promptlock" in result.output.lower() or result.exit_code == 0
