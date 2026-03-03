"""Unit tests for promptlock/local/config.py — .promptlock.toml parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from promptlock.local.config import (
    CONFIG_FILENAME,
    EnvironmentConfig,
    ProjectConfig,
    load_config,
    write_default_config,
)


# ---------------------------------------------------------------------------
# load_config — file absent
# ---------------------------------------------------------------------------

class TestLoadConfigMissing:
    def test_returns_default_project_config(self, tmp_path: Path):
        cfg = load_config(tmp_path)
        assert isinstance(cfg, ProjectConfig)
        assert cfg.default_environment == "development"
        assert cfg.name is None
        assert cfg.remote is None

    def test_default_env_names_are_builtins(self, tmp_path: Path):
        cfg = load_config(tmp_path)
        names = cfg.env_names()
        assert "development" in names
        assert "staging" in names
        assert "production" in names


# ---------------------------------------------------------------------------
# load_config — valid TOML
# ---------------------------------------------------------------------------

FULL_TOML = """\
[project]
name = "my-project"
remote = "https://api.promptlock.io"

[environments]
default = "development"

[environments.development]
model = "claude-3-5-sonnet"

[environments.staging]
model = "claude-3-5-sonnet"

[environments.production]
model = "claude-3-opus"
"""

CUSTOM_ENV_TOML = """\
[environments]
default = "canary"

[environments.canary]
model = "gpt-4o"
type = "custom"
"""


class TestLoadConfigFull:
    def _write(self, tmp_path: Path, content: str) -> Path:
        config_path = tmp_path / CONFIG_FILENAME
        config_path.write_text(content, encoding="utf-8")
        return config_path

    def test_project_name(self, tmp_path: Path):
        self._write(tmp_path, FULL_TOML)
        cfg = load_config(tmp_path)
        assert cfg.name == "my-project"

    def test_project_remote(self, tmp_path: Path):
        self._write(tmp_path, FULL_TOML)
        cfg = load_config(tmp_path)
        assert cfg.remote == "https://api.promptlock.io"

    def test_default_environment(self, tmp_path: Path):
        self._write(tmp_path, FULL_TOML)
        cfg = load_config(tmp_path)
        assert cfg.default_environment == "development"

    def test_environments_parsed(self, tmp_path: Path):
        self._write(tmp_path, FULL_TOML)
        cfg = load_config(tmp_path)
        assert "development" in cfg.environments
        assert "staging" in cfg.environments
        assert "production" in cfg.environments

    def test_model_extracted(self, tmp_path: Path):
        self._write(tmp_path, FULL_TOML)
        cfg = load_config(tmp_path)
        assert cfg.environments["development"].model == "claude-3-5-sonnet"
        assert cfg.environments["production"].model == "claude-3-opus"

    def test_env_names_from_config(self, tmp_path: Path):
        self._write(tmp_path, FULL_TOML)
        cfg = load_config(tmp_path)
        assert set(cfg.env_names()) == {"development", "staging", "production"}

    def test_custom_environment(self, tmp_path: Path):
        self._write(tmp_path, CUSTOM_ENV_TOML)
        cfg = load_config(tmp_path)
        assert "canary" in cfg.environments
        assert cfg.environments["canary"].type == "custom"


# ---------------------------------------------------------------------------
# get_env
# ---------------------------------------------------------------------------

class TestGetEnv:
    def _write(self, tmp_path: Path, content: str) -> "ProjectConfig":
        path = tmp_path / CONFIG_FILENAME
        path.write_text(content, encoding="utf-8")
        return load_config(tmp_path)

    def test_returns_known_env(self, tmp_path: Path):
        cfg = self._write(tmp_path, FULL_TOML)
        env = cfg.get_env("development")
        assert env is not None
        assert env.model == "claude-3-5-sonnet"

    def test_returns_builtin_bare_config_for_unlisted_builtin(self, tmp_path: Path):
        # 'archived' is a builtin but not in FULL_TOML
        cfg = self._write(tmp_path, FULL_TOML)
        env = cfg.get_env("archived")
        assert env is not None
        assert env.name == "archived"

    def test_returns_none_for_unknown_env(self, tmp_path: Path):
        cfg = self._write(tmp_path, FULL_TOML)
        assert cfg.get_env("unknown-xyz") is None


# ---------------------------------------------------------------------------
# write_default_config
# ---------------------------------------------------------------------------

class TestWriteDefaultConfig:
    def test_creates_file_if_absent(self, tmp_path: Path):
        path = write_default_config(tmp_path)
        assert path.exists()
        content = path.read_text()
        assert "[environments]" in content
        assert "development" in content

    def test_does_not_overwrite_existing(self, tmp_path: Path):
        config_path = tmp_path / CONFIG_FILENAME
        config_path.write_text("custom = true", encoding="utf-8")
        write_default_config(tmp_path)
        assert config_path.read_text() == "custom = true"

    def test_returned_path_is_correct(self, tmp_path: Path):
        path = write_default_config(tmp_path)
        assert path == tmp_path / CONFIG_FILENAME

    def test_default_config_is_valid_toml(self, tmp_path: Path):
        write_default_config(tmp_path)
        # Should parse without errors
        cfg = load_config(tmp_path)
        assert cfg.default_environment == "development"


# ---------------------------------------------------------------------------
# EnvironmentConfig
# ---------------------------------------------------------------------------

class TestEnvironmentConfig:
    def test_is_builtin_development(self):
        env = EnvironmentConfig(name="development")
        assert env.is_builtin() is True

    def test_is_builtin_custom(self):
        env = EnvironmentConfig(name="canary")
        assert env.is_builtin() is False

    def test_default_type(self):
        env = EnvironmentConfig(name="test")
        assert env.type == "custom"


# ---------------------------------------------------------------------------
# load_config — edge cases for coverage
# ---------------------------------------------------------------------------

class TestLoadConfigEdgeCases:
    def test_non_dict_env_entry_is_skipped(self, tmp_path: Path):
        """Environments section entries that are not dicts are silently skipped."""
        toml_content = """\
[project]
name = "test"

[environments]
default = "development"
invalid_entry = "this is a string not a table"

[environments.development]
model = "gpt-4"
"""
        config_path = tmp_path / CONFIG_FILENAME
        config_path.write_text(toml_content)

        cfg = load_config(tmp_path)
        # "invalid_entry" should be skipped, "development" should be present
        assert "development" in cfg.environments

    def test_load_config_exception_returns_default(self, tmp_path: Path, monkeypatch):
        """If _load_toml_text raises an unexpected exception, return default config."""
        from promptlock.local import config as config_module
        config_path = tmp_path / CONFIG_FILENAME
        config_path.write_text("[project]\nname = 'x'\n")

        def _boom(path):
            raise RuntimeError("unexpected error")

        monkeypatch.setattr(config_module, "_load_toml_text", _boom)
        cfg = load_config(tmp_path)
        assert isinstance(cfg, ProjectConfig)
        assert cfg.name is None  # default config
