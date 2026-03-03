"""CLI tests for: promptlock logout"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from promptlock.main import cli


@patch("promptlock.commands.logout.RegistryClient")
def test_logout_clears_credentials(MockClient, tmp_path: Path, monkeypatch):
    instance = MockClient.return_value
    instance.logout.return_value = None

    import promptlock.auth as auth_module
    config_dir = tmp_path / ".promptlock_home"
    config_dir.mkdir()
    config_file = config_dir / "config"
    monkeypatch.setattr(auth_module, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(auth_module, "_CONFIG_FILE", config_file)

    auth_module.save_credentials(token="old_token", email="a@b.com", org_id="o1")

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["logout"], catch_exceptions=False)
    assert result.exit_code == 0
    assert auth_module.get_token() is None


@patch("promptlock.commands.logout.RegistryClient")
def test_logout_without_token(MockClient, tmp_path: Path, monkeypatch):
    import promptlock.auth as auth_module
    config_dir = tmp_path / ".promptlock_home2"
    config_dir.mkdir()
    monkeypatch.setattr(auth_module, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(auth_module, "_CONFIG_FILE", config_dir / "config")

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["logout"], catch_exceptions=False)
    assert result.exit_code == 0


@patch("promptlock.commands.logout.RegistryClient")
def test_logout_revoke_server_error_still_clears_local(MockClient, tmp_path: Path, monkeypatch):
    """Server revocation failure should not prevent local cleanup."""
    from promptlock.api.client import RegistryClientError
    instance = MockClient.return_value
    instance.logout.side_effect = RegistryClientError(500, "server error")

    import promptlock.auth as auth_module
    config_dir = tmp_path / ".promptlock_home3"
    config_dir.mkdir()
    monkeypatch.setattr(auth_module, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(auth_module, "_CONFIG_FILE", config_dir / "config")
    auth_module.save_credentials(token="tok", email="a@b.com", org_id="o1")

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["logout"], catch_exceptions=False)
    assert result.exit_code == 0
    assert auth_module.get_token() is None
