"""API tests for: /v1/auth/* endpoints"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REGISTER_PAYLOAD = {
    "email": "alice@example.com",
    "password": "password123",
    "org_name": "acme",
}

REGISTER_PAYLOAD_2 = {
    "email": "bob@example.com",
    "password": "securepass",
    "org_name": "globex",
}


async def _register(client: AsyncClient, payload: dict = None) -> dict:
    payload = payload or REGISTER_PAYLOAD
    resp = await client.post("/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post("/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# POST /v1/auth/register
# ---------------------------------------------------------------------------


class TestRegister:
    async def test_register_success(self, client: AsyncClient):
        resp = await client.post("/v1/auth/register", json=REGISTER_PAYLOAD)
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert data["email"] == "alice@example.com"

    async def test_register_returns_org_id(self, client: AsyncClient):
        resp = await client.post("/v1/auth/register", json=REGISTER_PAYLOAD)
        assert "org_id" in resp.json()

    async def test_register_duplicate_email_409(self, client: AsyncClient):
        await client.post("/v1/auth/register", json=REGISTER_PAYLOAD)
        resp = await client.post("/v1/auth/register", json=REGISTER_PAYLOAD)
        assert resp.status_code == 409

    async def test_register_missing_fields_422(self, client: AsyncClient):
        resp = await client.post("/v1/auth/register", json={"email": "x@y.com"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /v1/auth/login
# ---------------------------------------------------------------------------


class TestLogin:
    async def test_login_success(self, client: AsyncClient):
        await _register(client)
        resp = await client.post(
            "/v1/auth/login",
            json={"email": "alice@example.com", "password": "password123"},
        )
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    async def test_login_wrong_password_401(self, client: AsyncClient):
        await _register(client)
        resp = await client.post(
            "/v1/auth/login",
            json={"email": "alice@example.com", "password": "wrongpass"},
        )
        assert resp.status_code == 401

    async def test_login_unknown_email_401(self, client: AsyncClient):
        resp = await client.post(
            "/v1/auth/login",
            json={"email": "nobody@x.com", "password": "pass"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /v1/auth/me
# ---------------------------------------------------------------------------


class TestMe:
    async def test_me_returns_user_info(self, client: AsyncClient):
        data = await _register(client)
        token = data["access_token"]  # use token from registration
        resp = await client.get(
            "/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == "alice@example.com"

    async def test_me_no_token_401(self, client: AsyncClient):
        resp = await client.get("/v1/auth/me")
        assert resp.status_code == 401

    async def test_me_invalid_token_401(self, client: AsyncClient):
        resp = await client.get(
            "/v1/auth/me",
            headers={"Authorization": "Bearer not.a.valid.jwt"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /v1/auth/logout
# ---------------------------------------------------------------------------


class TestLogout:
    async def test_logout_success(self, client: AsyncClient):
        data = await _register(client)
        token = data["access_token"]  # use token from registration
        resp = await client.post(
            "/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code in (200, 204)

    async def test_logout_no_token_401(self, client: AsyncClient):
        resp = await client.post("/v1/auth/logout")
        assert resp.status_code == 401
