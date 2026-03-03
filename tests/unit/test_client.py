"""Unit tests for promptlock/api/client.py — RegistryClient with respx mocks."""

from __future__ import annotations

import pytest
import respx
import httpx

from promptlock.api.client import RegistryClient, RegistryClientError


BASE = "http://test.local"


@pytest.fixture
def client() -> RegistryClient:
    return RegistryClient(base_url=BASE, token="test-jwt")


@pytest.fixture
def anon_client() -> RegistryClient:
    return RegistryClient(base_url=BASE)


# ---------------------------------------------------------------------------
# RegistryClientError
# ---------------------------------------------------------------------------

class TestRegistryClientError:
    def test_str(self):
        err = RegistryClientError(404, "not found")
        assert "404" in str(err)
        assert "not found" in str(err)

    def test_attributes(self):
        err = RegistryClientError(401, "unauthorized")
        assert err.status_code == 401
        assert err.detail == "unauthorized"


# ---------------------------------------------------------------------------
# _headers
# ---------------------------------------------------------------------------

class TestHeaders:
    def test_bearer_token_present_when_token_set(self, client: RegistryClient):
        h = client._headers()
        assert h["Authorization"] == "Bearer test-jwt"

    def test_no_auth_header_when_no_token(self, anon_client: RegistryClient):
        h = anon_client._headers()
        assert "Authorization" not in h

    def test_extra_headers_merged(self, client: RegistryClient):
        h = client._headers({"X-Custom": "value"})
        assert h["X-Custom"] == "value"
        assert h["Authorization"] == "Bearer test-jwt"


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

class TestAuthEndpoints:
    @respx.mock
    def test_register(self, client: RegistryClient):
        respx.post(f"{BASE}/v1/auth/register").mock(
            return_value=httpx.Response(200, json={"user_id": "u1", "email": "a@b.com"})
        )
        result = client.register("a@b.com", "pass", "myorg")
        assert result["email"] == "a@b.com"

    @respx.mock
    def test_login(self, client: RegistryClient):
        respx.post(f"{BASE}/v1/auth/login").mock(
            return_value=httpx.Response(200, json={"access_token": "tok", "org_id": "org1", "email": "a@b.com"})
        )
        result = client.login("a@b.com", "pass")
        assert result["access_token"] == "tok"

    @respx.mock
    def test_logout(self, client: RegistryClient):
        respx.post(f"{BASE}/v1/auth/logout").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        client.logout()  # Should not raise

    @respx.mock
    def test_me(self, client: RegistryClient):
        respx.get(f"{BASE}/v1/auth/me").mock(
            return_value=httpx.Response(200, json={"email": "a@b.com", "org_id": "org1"})
        )
        result = client.me()
        assert result["email"] == "a@b.com"


# ---------------------------------------------------------------------------
# Prompt endpoints
# ---------------------------------------------------------------------------

class TestPromptEndpoints:
    @respx.mock
    def test_create_prompt(self, client: RegistryClient):
        respx.post(f"{BASE}/v1/prompts").mock(
            return_value=httpx.Response(200, json={"id": "p1", "name": "summary"})
        )
        result = client.create_prompt("summary", "prompts/summary.txt")
        assert result["id"] == "p1"

    @respx.mock
    def test_list_prompts(self, client: RegistryClient):
        respx.get(f"{BASE}/v1/prompts").mock(
            return_value=httpx.Response(200, json={"items": [], "cursor": None})
        )
        result = client.list_prompts()
        assert result["items"] == []

    @respx.mock
    def test_push_version(self, client: RegistryClient):
        respx.post(f"{BASE}/v1/prompts/p1/versions").mock(
            return_value=httpx.Response(200, json={"id": "v1", "version_num": 1})
        )
        result = client.push_version(
            prompt_id="p1",
            sha256="abc",
            version_num=1,
            message="init",
            author="alice",
            environment="development",
            content=b"hello world",
        )
        assert result["version_num"] == 1

    @respx.mock
    def test_list_versions(self, client: RegistryClient):
        respx.get(f"{BASE}/v1/prompts/p1/versions").mock(
            return_value=httpx.Response(200, json={"items": [], "cursor": None})
        )
        result = client.list_versions("p1")
        assert "items" in result

    @respx.mock
    def test_get_version(self, client: RegistryClient):
        respx.get(f"{BASE}/v1/prompts/p1/versions/v1").mock(
            return_value=httpx.Response(200, json={"id": "v1", "version_num": 1, "template": "hello"})
        )
        result = client.get_version("p1", "v1")
        assert result["template"] == "hello"

    @respx.mock
    def test_get_prompt_by_path_found(self, client: RegistryClient):
        respx.get(f"{BASE}/v1/prompts").mock(
            return_value=httpx.Response(200, json={"items": [{"id": "p1", "path": "prompts/foo.txt"}], "cursor": None})
        )
        result = client.get_prompt_by_path("prompts/foo.txt")
        assert result["id"] == "p1"

    @respx.mock
    def test_get_prompt_by_path_not_found(self, client: RegistryClient):
        respx.get(f"{BASE}/v1/prompts").mock(
            return_value=httpx.Response(200, json={"items": [], "cursor": None})
        )
        result = client.get_prompt_by_path("prompts/missing.txt")
        assert result is None


# ---------------------------------------------------------------------------
# Environments & Promotions (v0.3)
# ---------------------------------------------------------------------------

class TestEnvironmentEndpoints:
    @respx.mock
    def test_list_environments(self, client: RegistryClient):
        respx.get(f"{BASE}/v1/environments").mock(
            return_value=httpx.Response(200, json={"items": [], "cursor": None})
        )
        result = client.list_environments()
        assert "items" in result

    @respx.mock
    def test_create_environment(self, client: RegistryClient):
        respx.post(f"{BASE}/v1/environments").mock(
            return_value=httpx.Response(200, json={"id": "e1", "name": "staging"})
        )
        result = client.create_environment("staging", "builtin")
        assert result["name"] == "staging"

    @respx.mock
    def test_create_promotion(self, client: RegistryClient):
        respx.post(f"{BASE}/v1/promotions").mock(
            return_value=httpx.Response(200, json={"id": "pr1", "status": "approved"})
        )
        result = client.create_promotion(
            prompt_path="prompts/foo.txt",
            from_env="development",
            to_env="staging",
            version_num=1,
        )
        assert result["status"] == "approved"

    @respx.mock
    def test_list_promotions(self, client: RegistryClient):
        respx.get(f"{BASE}/v1/promotions").mock(
            return_value=httpx.Response(200, json={"items": [], "cursor": None})
        )
        result = client.list_promotions()
        assert "items" in result

    @respx.mock
    def test_update_promotion(self, client: RegistryClient):
        respx.patch(f"{BASE}/v1/promotions/pr1").mock(
            return_value=httpx.Response(200, json={"id": "pr1", "status": "rejected"})
        )
        result = client.update_promotion("pr1", "rejected", comment="not ready")
        assert result["status"] == "rejected"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @respx.mock
    def test_raises_on_404(self, client: RegistryClient):
        respx.get(f"{BASE}/v1/auth/me").mock(
            return_value=httpx.Response(404, json={"detail": "not found"})
        )
        with pytest.raises(RegistryClientError) as exc_info:
            client.me()
        assert exc_info.value.status_code == 404

    @respx.mock
    def test_raises_on_401(self, client: RegistryClient):
        respx.post(f"{BASE}/v1/auth/login").mock(
            return_value=httpx.Response(401, json={"detail": "bad credentials"})
        )
        with pytest.raises(RegistryClientError) as exc_info:
            client.login("bad@x.com", "wrong")
        assert exc_info.value.status_code == 401
        assert "bad credentials" in exc_info.value.detail

    @respx.mock
    def test_raises_on_500_non_json(self, client: RegistryClient):
        respx.get(f"{BASE}/v1/auth/me").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        with pytest.raises(RegistryClientError) as exc_info:
            client.me()
        assert exc_info.value.status_code == 500

    @respx.mock
    def test_health(self, client: RegistryClient):
        respx.get(f"{BASE}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        result = client.health()
        assert result["status"] == "ok"
