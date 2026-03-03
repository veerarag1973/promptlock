"""API tests for: /v1/environments/* and /v1/promotions/* endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _setup(client: AsyncClient, suffix: str) -> str:
    """Register, login, and return JWT token."""
    payload = {
        "email": f"env_user_{suffix}@test.io",
        "password": "pass1234",
        "org_name": f"env_org_{suffix}",
    }
    resp = await client.post("/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# GET /v1/environments
# ---------------------------------------------------------------------------


class TestListEnvironments:
    async def test_list_environments_unauthenticated_401(self, client: AsyncClient):
        resp = await client.get("/v1/environments")
        assert resp.status_code == 401

    async def test_list_environments_empty_new_org(self, client: AsyncClient):
        token = await _setup(client, "le1")
        resp = await client.get("/v1/environments", headers=_auth(token))
        assert resp.status_code == 200
        assert "items" in resp.json()

    async def test_list_environments_after_create(self, client: AsyncClient):
        token = await _setup(client, "le2")
        await client.post(
            "/v1/environments",
            json={"name": "canary", "type": "custom", "config_json": {}},
            headers=_auth(token),
        )
        resp = await client.get("/v1/environments", headers=_auth(token))
        assert resp.status_code == 200
        names = [e["name"] for e in resp.json()["items"]]
        assert "canary" in names


# ---------------------------------------------------------------------------
# POST /v1/environments
# ---------------------------------------------------------------------------


class TestCreateEnvironment:
    async def test_create_environment_success(self, client: AsyncClient):
        token = await _setup(client, "ce1")
        resp = await client.post(
            "/v1/environments",
            json={"name": "staging-v2", "type": "custom", "config_json": {"key": "val"}},
            headers=_auth(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "staging-v2"
        assert data["type"] == "custom"

    async def test_create_environment_returns_id(self, client: AsyncClient):
        token = await _setup(client, "ce2")
        resp = await client.post(
            "/v1/environments",
            json={"name": "my-env", "type": "custom", "config_json": {}},
            headers=_auth(token),
        )
        assert "id" in resp.json()

    async def test_create_environment_duplicate_409(self, client: AsyncClient):
        token = await _setup(client, "ce3")
        payload = {"name": "unique-env", "type": "custom", "config_json": {}}
        await client.post("/v1/environments", json=payload, headers=_auth(token))
        resp = await client.post("/v1/environments", json=payload, headers=_auth(token))
        assert resp.status_code == 409

    async def test_create_environment_no_auth_401(self, client: AsyncClient):
        resp = await client.post(
            "/v1/environments",
            json={"name": "x", "type": "custom", "config_json": {}},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /v1/promotions
# ---------------------------------------------------------------------------


class TestCreatePromotion:
    async def test_create_promotion_success(self, client: AsyncClient):
        token = await _setup(client, "promo1")
        resp = await client.post(
            "/v1/promotions",
            json={
                "prompt_path": "prompts/foo.txt",
                "from_environment": "development",
                "to_environment": "staging",
                "version_num": 1,
                "sha256": "abc123",
            },
            headers=_auth(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        # v0.5: promotions start as pending, require Reviewer approval
        assert data["status"] == "pending"
        assert data["prompt_path"] == "prompts/foo.txt"

    async def test_create_promotion_returns_pending(self, client: AsyncClient):
        """v0.5: all new promotion requests start in 'pending' status."""
        token = await _setup(client, "promo2")
        resp = await client.post(
            "/v1/promotions",
            json={
                "prompt_path": "prompts/bar.txt",
                "from_environment": "staging",
                "to_environment": "production",
                "version_num": 2,
                "sha256": "deadbeef",
            },
            headers=_auth(token),
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "pending"

    async def test_create_promotion_no_auth_401(self, client: AsyncClient):
        resp = await client.post(
            "/v1/promotions",
            json={
                "prompt_path": "p.txt",
                "from_environment": "dev",
                "to_environment": "staging",
                "version_num": 1,
                "sha256": "",
            },
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /v1/promotions
# ---------------------------------------------------------------------------


class TestListPromotions:
    async def test_list_promotions_empty(self, client: AsyncClient):
        token = await _setup(client, "lpromo1")
        resp = await client.get("/v1/promotions", headers=_auth(token))
        assert resp.status_code == 200
        assert "items" in resp.json()

    async def test_list_promotions_returns_created(self, client: AsyncClient):
        token = await _setup(client, "lpromo2")
        await client.post(
            "/v1/promotions",
            json={
                "prompt_path": "prompts/check.txt",
                "from_environment": "development",
                "to_environment": "staging",
                "version_num": 1,
                "sha256": "sha1",
            },
            headers=_auth(token),
        )
        resp = await client.get("/v1/promotions", headers=_auth(token))
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1
        assert items[0]["prompt_path"] == "prompts/check.txt"

    async def test_list_promotions_filter_by_path(self, client: AsyncClient):
        token = await _setup(client, "lpromo3")
        for path in ["prompts/a.txt", "prompts/b.txt"]:
            await client.post(
                "/v1/promotions",
                json={
                    "prompt_path": path,
                    "from_environment": "development",
                    "to_environment": "staging",
                    "version_num": 1,
                    "sha256": "x",
                },
                headers=_auth(token),
            )
        resp = await client.get(
            "/v1/promotions",
            params={"prompt_path": "prompts/a.txt"},
            headers=_auth(token),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        for item in items:
            assert item["prompt_path"] == "prompts/a.txt"


# ---------------------------------------------------------------------------
# PATCH /v1/promotions/{id}
# ---------------------------------------------------------------------------


class TestUpdatePromotion:
    async def test_update_promotion_status(self, client: AsyncClient):
        token = await _setup(client, "upromo1")
        create_resp = await client.post(
            "/v1/promotions",
            json={
                "prompt_path": "prompts/update_me.txt",
                "from_environment": "development",
                "to_environment": "staging",
                "version_num": 1,
                "sha256": "abc",
            },
            headers=_auth(token),
        )
        promo_id = create_resp.json()["id"]
        patch_resp = await client.patch(
            f"/v1/promotions/{promo_id}",
            json={"status": "rejected", "comment": "not ready"},
            headers=_auth(token),
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["status"] == "rejected"

    async def test_update_promotion_not_found(self, client: AsyncClient):
        token = await _setup(client, "upromo2")
        resp = await client.patch(
            "/v1/promotions/nonexistent-id",
            json={"status": "rejected", "comment": ""},
            headers=_auth(token),
        )
        assert resp.status_code == 404

    async def test_update_promotion_no_auth_401(self, client: AsyncClient):
        resp = await client.patch(
            "/v1/promotions/some_id",
            json={"status": "rejected", "comment": ""},
        )
        assert resp.status_code == 401
