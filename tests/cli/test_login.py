"""CLI tests for: promptlock login"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from promptlock.main import cli


MOCK_LOGIN_OK = {"access_token": "tok123", "org_id": "org_abc", "email": "user@example.com"}
MOCK_REGISTER_OK = {"user_id": "u1", "email": "user@example.com", "org_id": "org_abc", "access_token": "tok123"}


@patch("promptlock.commands.login.RegistryClient")
def test_login_success(MockClient, tmp_path: Path):
    instance = MockClient.return_value
    instance.login.return_value = MOCK_LOGIN_OK
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["login"],
            input="user@example.com\npassword123\n",
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    assert "success" in result.output.lower() or "logged in" in result.output.lower() or result.exit_code == 0


@patch("promptlock.commands.login.RegistryClient")
def test_login_bad_credentials(MockClient, tmp_path: Path):
    from promptlock.api.client import RegistryClientError
    instance = MockClient.return_value
    instance.login.side_effect = RegistryClientError(401, "Invalid credentials")
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["login"],
            input="bad@example.com\nwrongpass\n",
        )
    assert result.exit_code != 0 or "error" in result.output.lower() or "invalid" in result.output.lower()


@patch("promptlock.commands.login.RegistryClient")
def test_login_register_flag(MockClient, tmp_path: Path):
    instance = MockClient.return_value
    instance.register.return_value = MOCK_REGISTER_OK
    instance.login.return_value = MOCK_LOGIN_OK
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["login", "--register"],
            input="user@example.com\npassword123\nmyorg\n",
            catch_exceptions=False,
        )
    assert result.exit_code == 0


@patch("promptlock.commands.login.RegistryClient")
def test_login_saves_credentials(MockClient, tmp_path: Path, monkeypatch):
    instance = MockClient.return_value
    instance.login.return_value = MOCK_LOGIN_OK

    import promptlock.auth as auth_module
    config_dir = tmp_path / ".promptlock_home"
    config_dir.mkdir()
    monkeypatch.setattr(auth_module, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(auth_module, "_CONFIG_FILE", config_dir / "config")

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(
            cli,
            ["login"],
            input="user@example.com\npassword123\n",
            catch_exceptions=False,
        )
    from promptlock.auth import get_token
    assert get_token() == "tok123"
