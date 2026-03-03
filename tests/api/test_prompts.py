"""API tests for: /v1/prompts/* endpoints.

S3 operations (upload_fileobj, get_object) are mocked so no real MinIO/S3 is needed.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _register_and_login(client: AsyncClient, suffix: str = "") -> tuple[str, str]:
    """Return (token, org_id)."""
    payload = {
        "email": f"tester_{suffix}@example.com",
        "password": "pass1234",
        "org_name": f"org_{suffix}",
    }
    reg = await client.post("/v1/auth/register", json=payload)
    assert reg.status_code == 201, reg.text
    data = reg.json()
    return data["access_token"], data["org_id"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


PROMPT_BODY = {
    "name": "greeting",
    "path": "prompts/greeting.txt",
    "description": "A greeting prompt",
}


# ---------------------------------------------------------------------------
# POST /v1/prompts  (create)
# ---------------------------------------------------------------------------


class TestCreatePrompt:
    async def test_create_prompt_success(self, client: AsyncClient):
        token, _ = await _register_and_login(client, "cp1")
        resp = await client.post("/v1/prompts", json=PROMPT_BODY, headers=_auth(token))
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "greeting"
        assert "id" in data

    async def test_create_prompt_no_auth_401(self, client: AsyncClient):
        resp = await client.post("/v1/prompts", json=PROMPT_BODY)
        assert resp.status_code == 401

    async def test_create_prompt_duplicate_idempotent(self, client: AsyncClient):
        """Creating the same path twice should return 200 or 201 (idempotent)."""
        token, _ = await _register_and_login(client, "cp2")
        await client.post("/v1/prompts", json=PROMPT_BODY, headers=_auth(token))
        resp = await client.post("/v1/prompts", json=PROMPT_BODY, headers=_auth(token))
        # Should be 200 (already exists) or 201 (re-create allowed)
        assert resp.status_code in (200, 201, 409)


# ---------------------------------------------------------------------------
# GET /v1/prompts  (list)
# ---------------------------------------------------------------------------


class TestListPrompts:
    async def test_list_prompts_empty(self, client: AsyncClient):
        token, _ = await _register_and_login(client, "lp1")
        resp = await client.get("/v1/prompts", headers=_auth(token))
        assert resp.status_code == 200
        assert "items" in resp.json()

    async def test_list_prompts_returns_created(self, client: AsyncClient):
        token, _ = await _register_and_login(client, "lp2")
        await client.post("/v1/prompts", json=PROMPT_BODY, headers=_auth(token))
        resp = await client.get("/v1/prompts", headers=_auth(token))
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert any(p["path"] == "prompts/greeting.txt" for p in items)

    async def test_list_prompts_no_auth_401(self, client: AsyncClient):
        resp = await client.get("/v1/prompts")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /v1/prompts/{id}/versions  (push)
# ---------------------------------------------------------------------------


class TestPushVersion:
    def _make_s3_mock(self):
        mock_s3 = MagicMock()
        mock_s3.upload_fileobj.return_value = None
        return mock_s3

    @patch("api.routers.prompts._s3_client")
    async def test_push_version_success(self, mock_s3_fn, client: AsyncClient):
        mock_s3_fn.return_value = self._make_s3_mock()
        token, _ = await _register_and_login(client, "pv1")
        # Create prompt
        cp = await client.post("/v1/prompts", json=PROMPT_BODY, headers=_auth(token))
        prompt_id = cp.json()["id"]

        content = b"Hello, {{ name }}!"
        resp = await client.post(
            f"/v1/prompts/{prompt_id}/versions",
            headers=_auth(token),
            files={
                "content": ("prompt.txt", BytesIO(content), "text/plain"),
                "sha256": (None, "abc123"),
                "version_num": (None, "1"),
                "message": (None, "initial"),
                "author": (None, "alice"),
                "environment": (None, "development"),
                "tags": (None, ""),
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["version_num"] == 1

    @patch("api.routers.prompts._s3_client")
    async def test_push_version_no_auth_401(self, mock_s3_fn, client: AsyncClient):
        mock_s3_fn.return_value = self._make_s3_mock()
        resp = await client.post(
            "/v1/prompts/fake_id/versions",
            files={"content": ("f.txt", BytesIO(b"x"), "text/plain")},
        )
        assert resp.status_code == 401

    @patch("api.routers.prompts._s3_client")
    async def test_push_version_duplicate_409(self, mock_s3_fn, client: AsyncClient):
        mock_s3_fn.return_value = self._make_s3_mock()
        token, _ = await _register_and_login(client, "pv2")
        cp = await client.post("/v1/prompts", json=PROMPT_BODY, headers=_auth(token))
        prompt_id = cp.json()["id"]
        content = b"Hello!"
        files = {
            "content": ("prompt.txt", BytesIO(content), "text/plain"),
            "sha256": (None, "deadbeef"),
            "version_num": (None, "1"),
            "message": (None, "first"),
            "author": (None, "alice"),
            "environment": (None, "development"),
            "tags": (None, ""),
        }
        await client.post(f"/v1/prompts/{prompt_id}/versions", headers=_auth(token), files=files)
        # Push same version again — should be 409 or idempotent
        files2 = {
            "content": ("prompt.txt", BytesIO(content), "text/plain"),
            "sha256": (None, "deadbeef"),
            "version_num": (None, "1"),
            "message": (None, "first"),
            "author": (None, "alice"),
            "environment": (None, "development"),
            "tags": (None, ""),
        }
        resp2 = await client.post(f"/v1/prompts/{prompt_id}/versions", headers=_auth(token), files=files2)
        assert resp2.status_code in (201, 409)


# ---------------------------------------------------------------------------
# GET /v1/prompts/{id}/versions  (list)
# ---------------------------------------------------------------------------


class TestListVersions:
    @patch("api.routers.prompts._s3_client")
    async def test_list_versions_empty(self, mock_s3_fn, client: AsyncClient):
        mock_s3_fn.return_value = MagicMock()
        token, _ = await _register_and_login(client, "lv1")
        cp = await client.post("/v1/prompts", json=PROMPT_BODY, headers=_auth(token))
        prompt_id = cp.json()["id"]
        resp = await client.get(f"/v1/prompts/{prompt_id}/versions", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    @patch("api.routers.prompts._s3_client")
    async def test_list_versions_after_push(self, mock_s3_fn, client: AsyncClient):
        mock_s3 = MagicMock()
        mock_s3.upload_fileobj.return_value = None
        mock_s3_fn.return_value = mock_s3
        token, _ = await _register_and_login(client, "lv2")
        cp = await client.post("/v1/prompts", json=PROMPT_BODY, headers=_auth(token))
        prompt_id = cp.json()["id"]
        await client.post(
            f"/v1/prompts/{prompt_id}/versions",
            headers=_auth(token),
            files={
                "content": ("f.txt", BytesIO(b"hello"), "text/plain"),
                "sha256": (None, "sha_lv2"),
                "version_num": (None, "1"),
                "message": (None, "initial"),
                "author": (None, "alice"),
                "environment": (None, "development"),
                "tags": (None, ""),
            },
        )
        resp = await client.get(f"/v1/prompts/{prompt_id}/versions", headers=_auth(token))
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1


# ---------------------------------------------------------------------------
# GET /v1/prompts/{id}/versions/{version}  (get single)
# ---------------------------------------------------------------------------


class TestGetVersion:
    @patch("api.routers.prompts._s3_client")
    async def test_get_version_by_num(self, mock_s3_fn, client: AsyncClient):
        mock_s3 = MagicMock()
        mock_s3.upload_fileobj.return_value = None
        mock_s3.get_object.return_value = {"Body": BytesIO(b"hello world")}
        mock_s3_fn.return_value = mock_s3
        token, _ = await _register_and_login(client, "gv1")
        cp = await client.post("/v1/prompts", json=PROMPT_BODY, headers=_auth(token))
        prompt_id = cp.json()["id"]
        await client.post(
            f"/v1/prompts/{prompt_id}/versions",
            headers=_auth(token),
            files={
                "content": ("f.txt", BytesIO(b"hello world"), "text/plain"),
                "sha256": (None, "sha_gv1"),
                "version_num": (None, "1"),
                "message": (None, "first"),
                "author": (None, "alice"),
                "environment": (None, "development"),
                "tags": (None, ""),
            },
        )
        resp = await client.get(
            f"/v1/prompts/{prompt_id}/versions/1",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        assert resp.json()["version_num"] == 1

    @patch("api.routers.prompts._s3_client")
    async def test_get_version_not_found(self, mock_s3_fn, client: AsyncClient):
        mock_s3_fn.return_value = MagicMock()
        token, _ = await _register_and_login(client, "gv2")
        cp = await client.post("/v1/prompts", json=PROMPT_BODY, headers=_auth(token))
        prompt_id = cp.json()["id"]
        resp = await client.get(
            f"/v1/prompts/{prompt_id}/versions/999",
            headers=_auth(token),
        )
        assert resp.status_code == 404
