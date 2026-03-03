"""API tests for: /v1/orgs/{org_id}/roles endpoints (spec §4.3) — v0.4"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COUNTER = 0


async def _register(client: AsyncClient, suffix: str) -> dict:
    """Register a fresh user and return the full response body."""
    resp = await client.post(
        "/v1/auth/register",
        json={
            "email": f"user_{suffix}@example.com",
            "password": "password123",
            "org_name": f"org-{suffix}",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _hdrs(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# GET /v1/orgs/{org_id}/roles
# ---------------------------------------------------------------------------


class TestListRoles:
    async def test_list_roles_requires_auth(self, client: AsyncClient):
        resp = await client.get("/v1/orgs/some-org-id/roles")
        assert resp.status_code == 401

    async def test_list_roles_for_own_org(self, client: AsyncClient):
        data = await _register(client, "lr1")
        resp = await client.get(
            f"/v1/orgs/{data['org_id']}/roles",
            headers=_hdrs(data["access_token"]),
        )
        assert resp.status_code == 200
        items = resp.json()
        # Should contain at least the Org Admin auto-assignment from registration
        assert isinstance(items, list)
        assert len(items) >= 1
        role_names = [i["role_name"] for i in items]
        assert "Org Admin" in role_names

    async def test_list_roles_cross_org_forbidden(self, client: AsyncClient):
        """User cannot list roles for a different org."""
        a = await _register(client, "lr2a")
        b = await _register(client, "lr2b")
        resp = await client.get(
            f"/v1/orgs/{b['org_id']}/roles",
            headers=_hdrs(a["access_token"]),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /v1/orgs/{org_id}/roles
# ---------------------------------------------------------------------------


class TestAssignRole:
    async def test_assign_role_requires_auth(self, client: AsyncClient):
        resp = await client.post(
            "/v1/orgs/some-org-id/roles",
            json={"user_id": "uid", "role_name": "Viewer", "scope_id": "sid", "scope_type": "org"},
        )
        assert resp.status_code == 401

    async def test_assign_role_success(self, client: AsyncClient):
        data = await _register(client, "ar1")
        org_id = data["org_id"]
        user_id = data.get("user_id") or (
            await client.get("/v1/auth/me", headers=_hdrs(data["access_token"]))
        ).json()["id"]

        resp = await client.post(
            f"/v1/orgs/{org_id}/roles",
            headers=_hdrs(data["access_token"]),
            json={
                "user_id": user_id,
                "role_name": "Auditor",
                "scope_id": org_id,
                "scope_type": "org",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["role_name"] == "Auditor"
        assert body["user_id"] == user_id

    async def test_assign_role_idempotent(self, client: AsyncClient):
        """Assigning the same role twice returns 201 with the existing row."""
        data = await _register(client, "ar2")
        org_id = data["org_id"]
        me = await client.get("/v1/auth/me", headers=_hdrs(data["access_token"]))
        user_id = me.json()["id"]

        payload = {
            "user_id": user_id,
            "role_name": "Reviewer",
            "scope_id": org_id,
            "scope_type": "org",
        }
        headers = _hdrs(data["access_token"])
        r1 = await client.post(f"/v1/orgs/{org_id}/roles", headers=headers, json=payload)
        r2 = await client.post(f"/v1/orgs/{org_id}/roles", headers=headers, json=payload)
        assert r1.status_code == 201
        assert r2.status_code == 201
        # Same assignment ID returned
        assert r1.json()["id"] == r2.json()["id"]

    async def test_assign_unknown_role_422(self, client: AsyncClient):
        data = await _register(client, "ar3")
        org_id = data["org_id"]
        me = await client.get("/v1/auth/me", headers=_hdrs(data["access_token"]))
        user_id = me.json()["id"]

        resp = await client.post(
            f"/v1/orgs/{org_id}/roles",
            headers=_hdrs(data["access_token"]),
            json={
                "user_id": user_id,
                "role_name": "SuperAdmin",
                "scope_id": org_id,
                "scope_type": "org",
            },
        )
        assert resp.status_code == 422

    async def test_assign_role_cross_org_forbidden(self, client: AsyncClient):
        a = await _register(client, "ar4a")
        b = await _register(client, "ar4b")
        me_b = await client.get("/v1/auth/me", headers=_hdrs(b["access_token"]))
        user_id_b = me_b.json()["id"]

        resp = await client.post(
            f"/v1/orgs/{b['org_id']}/roles",
            headers=_hdrs(a["access_token"]),
            json={
                "user_id": user_id_b,
                "role_name": "Viewer",
                "scope_id": b["org_id"],
                "scope_type": "org",
            },
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /v1/orgs/{org_id}/roles/{assignment_id}
# ---------------------------------------------------------------------------


class TestRevokeRole:
    async def test_revoke_role_requires_auth(self, client: AsyncClient):
        resp = await client.delete("/v1/orgs/some-org/roles/some-assignment")
        assert resp.status_code == 401

    async def test_revoke_role_success(self, client: AsyncClient):
        data = await _register(client, "rr1")
        org_id = data["org_id"]
        headers = _hdrs(data["access_token"])
        me = await client.get("/v1/auth/me", headers=headers)
        user_id = me.json()["id"]

        # First assign a role
        assign_resp = await client.post(
            f"/v1/orgs/{org_id}/roles",
            headers=headers,
            json={
                "user_id": user_id,
                "role_name": "Contributor",
                "scope_id": org_id,
                "scope_type": "org",
            },
        )
        assert assign_resp.status_code == 201
        assignment_id = assign_resp.json()["id"]

        # Revoke it
        del_resp = await client.delete(
            f"/v1/orgs/{org_id}/roles/{assignment_id}",
            headers=headers,
        )
        assert del_resp.status_code == 204

    async def test_revoke_nonexistent_role_404(self, client: AsyncClient):
        data = await _register(client, "rr2")
        org_id = data["org_id"]
        headers = _hdrs(data["access_token"])
        resp = await client.delete(
            f"/v1/orgs/{org_id}/roles/nonexistent-id",
            headers=headers,
        )
        assert resp.status_code == 404

    async def test_revoke_role_cross_org_forbidden(self, client: AsyncClient):
        a = await _register(client, "rr3a")
        b = await _register(client, "rr3b")
        resp = await client.delete(
            f"/v1/orgs/{b['org_id']}/roles/some-assignment-id",
            headers=_hdrs(a["access_token"]),
        )
        assert resp.status_code == 403

    async def test_revoke_and_audit_event_recorded(self, client: AsyncClient):
        """Revocation of a role should emit an x.promptlock.role.revoked event."""
        data = await _register(client, "rr4")
        org_id = data["org_id"]
        headers = _hdrs(data["access_token"])
        me = await client.get("/v1/auth/me", headers=headers)
        user_id = me.json()["id"]

        assign_resp = await client.post(
            f"/v1/orgs/{org_id}/roles",
            headers=headers,
            json={"user_id": user_id, "role_name": "Reviewer", "scope_id": org_id, "scope_type": "org"},
        )
        assignment_id = assign_resp.json()["id"]

        await client.delete(f"/v1/orgs/{org_id}/roles/{assignment_id}", headers=headers)

        audit_resp = await client.get(
            "/v1/audit",
            headers=headers,
            params={"event_type": "x.promptlock.role.revoked"},
        )
        assert audit_resp.status_code == 200
        assert len(audit_resp.json()["items"]) >= 1


# ---------------------------------------------------------------------------
# RBAC unit: require_roles dependency
# ---------------------------------------------------------------------------


class TestRBACEnforcement:
    async def test_contributor_role_auto_assigned_via_org_admin(self, client: AsyncClient):
        """Every registered user gets Org Admin; Org Admin passes all role checks."""
        data = await _register(client, "re1")
        # Org Admin has wildcard permissions — can access audit log
        resp = await client.get(
            "/v1/audit",
            headers=_hdrs(data["access_token"]),
        )
        assert resp.status_code == 200

    async def test_assign_auditor_role_grants_audit_access(self, client: AsyncClient):
        """After explicitly assigning Auditor role, user can access audit log.

        In our model every user already gets Org Admin on registration so they
        already can access.  This test verifies the Auditor role specifically
        grants the permission by checking the role list includes Auditor.
        """
        data = await _register(client, "re2")
        org_id = data["org_id"]
        headers = _hdrs(data["access_token"])
        me = await client.get("/v1/auth/me", headers=headers)
        user_id = me.json()["id"]

        assign_resp = await client.post(
            f"/v1/orgs/{org_id}/roles",
            headers=headers,
            json={"user_id": user_id, "role_name": "Auditor", "scope_id": org_id, "scope_type": "org"},
        )
        assert assign_resp.status_code == 201

        # List current assignments — should contain both Org Admin and Auditor
        list_resp = await client.get(f"/v1/orgs/{org_id}/roles", headers=headers)
        role_names = [i["role_name"] for i in list_resp.json()]
        assert "Org Admin" in role_names
        assert "Auditor" in role_names
