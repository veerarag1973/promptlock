"""Unit tests for promptlock/auth.py — JWT token storage."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from promptlock.auth import (
    clear_credentials,
    get_email,
    get_org_id,
    get_registry_url,
    get_token,
    require_token,
    save_credentials,
)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect ~/.promptlock/config to a temp directory for each test."""
    config_dir = tmp_path / ".promptlock"
    config_dir.mkdir()
    config_file = config_dir / "config"

    import promptlock.auth as auth_module
    monkeypatch.setattr(auth_module, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(auth_module, "_CONFIG_FILE", config_file)


# ---------------------------------------------------------------------------
# Reading when nothing is stored
# ---------------------------------------------------------------------------

class TestEmptyConfig:
    def test_get_token_none(self):
        assert get_token() is None

    def test_get_email_none(self):
        assert get_email() is None

    def test_get_org_id_none(self):
        assert get_org_id() is None

    def test_get_registry_url_returns_default(self):
        url = get_registry_url()
        assert url.startswith("http")


# ---------------------------------------------------------------------------
# save_credentials → read back
# ---------------------------------------------------------------------------

class TestSaveCredentials:
    def test_saves_token(self):
        save_credentials(token="tok123", email="a@b.com", org_id="org1")
        assert get_token() == "tok123"

    def test_saves_email(self):
        save_credentials(token="t", email="user@example.com", org_id="o")
        assert get_email() == "user@example.com"

    def test_saves_org_id(self):
        save_credentials(token="t", email="e@x.com", org_id="org_abc")
        assert get_org_id() == "org_abc"

    def test_saves_custom_url(self):
        save_credentials(token="t", email="e@x.com", org_id="o", url="http://localhost:8000")
        assert get_registry_url() == "http://localhost:8000"

    def test_config_file_created(self):
        save_credentials(token="t", email="e@x.com", org_id="o")
        import promptlock.auth as m
        assert m._CONFIG_FILE.exists()

    def test_overwrite_existing_token(self):
        save_credentials(token="first", email="e@x.com", org_id="o")
        save_credentials(token="second", email="e@x.com", org_id="o")
        assert get_token() == "second"


# ---------------------------------------------------------------------------
# clear_credentials
# ---------------------------------------------------------------------------

class TestClearCredentials:
    def test_removes_token(self):
        save_credentials(token="tok", email="e@x.com", org_id="o")
        clear_credentials()
        assert get_token() is None

    def test_removes_email(self):
        save_credentials(token="tok", email="e@x.com", org_id="o")
        clear_credentials()
        assert get_email() is None

    def test_removes_org_id(self):
        save_credentials(token="tok", email="e@x.com", org_id="o")
        clear_credentials()
        assert get_org_id() is None

    def test_clear_when_no_credentials(self):
        clear_credentials()  # Should not raise


# ---------------------------------------------------------------------------
# require_token
# ---------------------------------------------------------------------------

class TestRequireToken:
    def test_returns_token_when_logged_in(self):
        save_credentials(token="valid_token", email="e@x.com", org_id="o")
        assert require_token() == "valid_token"

    def test_raises_system_exit_when_not_logged_in(self):
        with pytest.raises(SystemExit):
            require_token()
